from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, NamedTuple

from cachetools import LRUCache
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi import Request as HttpRequest
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from . import assets, diagnostics
from .document import Request, SelectionError, build_document
from .library import Library, LibraryUnavailable, Translation, UnknownTranslation
from .settings import Settings
from .typeset import Aborted, TypesetError, render_pdf, render_png

log = logging.getLogger(__name__)
TranslationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
PreviewKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class NoSniff:
    """Adds X-Content-Type-Options. Deliberately plain ASGI: Starlette's BaseHTTPMiddleware
    hides client disconnects from endpoints, which would defeat is_disconnected()."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_with_header(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        await self.app(
            scope, receive, send_with_header if scope["type"] == "http" else send
        )


class Static(StaticFiles):
    """Serves the UI. StaticFiles supplies ETag and Last-Modified and answers conditional requests with
    304; `no-cache` makes browsers use them on every load, so a new release is picked up at once."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class Preview(NamedTuple):
    pages: list[bytes]
    complete: bool  # False when the document continues beyond the pages shown


class RenderQuery(BaseModel):
    translation: list[TranslationId] = Field(
        min_length=1, max_length=2, description="1 translation, or 2 for parallel"
    )
    book: str = Field(pattern=r"^[0-9A-Z]{3}$")
    c1: int = Field(ge=1, le=200)
    v1: int = Field(1, ge=1, le=200)
    c2: int | None = Field(None, ge=1, le=200)
    v2: int | None = Field(None, ge=1, le=200)
    format: Literal["pdf", "txt"] = "pdf"
    paper: Literal["a4", "a5", "a6", "us-letter"] = "a4"
    size: float = Field(11.0, ge=8, le=16)
    title: str | None = Field(None, max_length=200)
    paragraphs: bool = False
    poetry: bool = True
    line_numbers: bool = True
    notes: bool = True
    line_spacing: Literal["1.5", "2"] = "1.5"
    colophon: bool = True
    download: bool = False


def _to_request(q: RenderQuery) -> Request:
    return Request(
        q.translation,
        q.book,
        q.c1,
        q.v1,
        q.c2,
        q.v2,
        q.paper,
        q.size,
        q.title,
        q.paragraphs,
        q.poetry,
        q.line_numbers,
        q.notes,
        q.line_spacing,
        q.colophon,
    )


def _summary(t: Translation) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "abbreviation": t.abbreviation,
        "lang": t.lang,
        "language": t.meta.language_name,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    library = Library(settings.db_path)
    gate = asyncio.Semaphore(settings.max_concurrent)
    # Rendered previews, keyed by a hash of exactly what was rendered. Only touched from the
    # event loop, so no locking. Sized in bytes.
    previews: LRUCache = LRUCache(
        maxsize=int(settings.preview_cache_mb * 1024 * 1024),
        getsizeof=lambda p: sum(map(len, p.pages)) or 1,
    )

    async def _run_self_test() -> None:
        app.state.health = await diagnostics.run(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not shutil.which(settings.typst_bin):
            log.error("Typst not found (%s): PDF output will fail", settings.typst_bin)
        if not settings.db_path.exists():
            log.warning(
                "No library at %s yet; run `manuscript-discovery ingest`",
                settings.db_path,
            )
        app.state.health = None
        check = asyncio.create_task(_run_self_test())
        yield
        check.cancel()
        with contextlib.suppress(
            asyncio.CancelledError
        ):  # let a Typst run in progress be killed cleanly
            await check
        library.close()

    app = FastAPI(
        title="Manuscript Discovery",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.exception_handler(LibraryUnavailable)
    async def unavailable(_, exc: LibraryUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    app.add_middleware(NoSniff)

    @app.get("/api/health")
    def health():
        """Typst version and whether CJK text can be drawn in previews (None while still checking)."""
        return app.state.health or {"status": "checking"}

    @app.get("/api/translations")
    def search(
        q: str | None = Query(None, max_length=100),
        lang: str | None = Query(None, max_length=8),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return [_summary(t) for t in library.search(q, lang, limit, offset)]

    @app.get("/api/translations/{translation_id}")
    def translation(translation_id: TranslationId):
        try:
            return _summary(library.get(translation_id))
        except UnknownTranslation:
            raise HTTPException(404, "Unknown translation") from None

    @app.get("/api/translations/{translation_id}/outline")
    def outline(translation_id: TranslationId):
        try:
            return [
                {"code": b.code, "name": b.name, "verses": list(b.verses)}
                for b in library.outline(translation_id)
            ]
        except UnknownTranslation:
            raise HTTPException(404, "Unknown translation") from None

    @app.get("/api/preview")
    async def preview(q: Annotated[RenderQuery, Query()], http: HttpRequest):
        """Render the first pages as low-resolution PNGs (screen preview, not for printing)."""
        try:
            doc = await run_in_threadpool(
                build_document, library, _to_request(q), settings.max_verses
            )
        except SelectionError as e:
            raise HTTPException(e.status, e.message) from None
        doc = doc.truncated(doc.preview_chars(settings.preview_pages))
        data = doc.typst_data()
        key = hashlib.sha256(
            json.dumps(
                [data, settings.preview_ppi, settings.preview_pages],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:32]
        hit = previews.get(key)
        if hit is None:
            started = time.perf_counter()
            try:
                pages = await render_png(
                    data, settings, gate, abort=http.is_disconnected
                )
            except Aborted:
                log.info("preview %s abandoned: client gone", key[:8])
                return Response(status_code=499)
            except TypesetError as e:
                raise HTTPException(500, str(e)) from None
            hit = Preview(
                pages[: settings.preview_pages],
                doc.complete and len(pages) <= settings.preview_pages,
            )
            with contextlib.suppress(
                ValueError
            ):  # larger than the whole cache: just don't keep it
                previews[key] = hit
            log.info(
                "preview %s rendered: %d pages, %.0f ms",
                key[:8],
                len(hit.pages),
                (time.perf_counter() - started) * 1000,
            )
        return {"key": key, "pages": len(hit.pages), "complete": hit.complete}

    @app.get("/api/preview/{key}/{page:int}.png")
    async def preview_page(key: PreviewKey, page: int):
        hit = previews.get(key)
        if hit is None or not 1 <= page <= len(hit.pages):
            raise HTTPException(
                404, "Preview expired; change a setting to render it again"
            )
        # The key is a hash of the content, so a page image never changes.
        return Response(
            hit.pages[page - 1],
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.get("/api/render")
    async def render(q: Annotated[RenderQuery, Query()], http: HttpRequest):
        try:
            doc = await run_in_threadpool(
                build_document, library, _to_request(q), settings.max_verses
            )
        except SelectionError as e:
            raise HTTPException(e.status, e.message) from None
        disposition = "attachment" if q.download else "inline"
        if q.format == "txt":
            return Response(
                doc.plain_text(),
                media_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f'{disposition}; filename="{doc.filename}.txt"'
                },
            )
        try:
            pdf = await render_pdf(
                doc.typst_data(), settings, gate, abort=http.is_disconnected
            )
        except Aborted:
            return Response(status_code=499)
        except TypesetError as e:
            raise HTTPException(500, str(e)) from None
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{disposition}; filename="{doc.filename}.pdf"'
            },
        )

    # Last, so every API route above wins; this serves the UI at "/".
    root = settings.static_dir or assets.serving_root(Path(__file__).parent / "static")
    log.info(
        "serving the UI from %s%s",
        root,
        " (unminified source: run `manuscript-discovery build-assets`)"
        if root.name != "dist"
        else "",
    )
    app.mount("/", Static(directory=root, html=True), name="ui")
    return app

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, NamedTuple

from cachetools import LRUCache
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi import Request as HttpRequest
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from . import __version__, assets, diagnostics
from .document import Request, SelectionError, build_document
from .library import Library, LibraryUnavailable, Translation, UnknownTranslation
from .security import SecurityHeaders, content_security_policy
from .settings import Settings
from .typeset import Aborted, Busy, Gate, TypesetError, render_pdf, render_png

log = logging.getLogger(__name__)
TranslationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
PreviewKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


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


@dataclass
class InFlightPreview:
    task: asyncio.Task[Preview]
    waiters: int = 0


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
    # Admit requests before loading chapters, and hold the slot until the response
    # is constructed. The separate compiler gate must never be acquired recursively.
    document_gate = Gate(settings.max_concurrent, settings.max_waiting)
    gate = asyncio.Semaphore(settings.max_concurrent)
    # Rendered previews, keyed by a hash of exactly what was rendered. Only touched from the
    # event loop, so no locking. Sized in bytes.
    previews: LRUCache = LRUCache(
        maxsize=int(settings.preview_cache_mb * 1024 * 1024),
        getsizeof=lambda p: sum(map(len, p.pages)) or 1,
    )

    in_flight: dict[str, InFlightPreview] = {}

    async def compile_preview(key: str, data: dict, complete: bool) -> Preview:
        started = time.perf_counter()
        pages = await render_png(data, settings, gate)
        hit = Preview(
            pages[: settings.preview_pages],
            complete and len(pages) <= settings.preview_pages,
        )
        with contextlib.suppress(ValueError):  # larger than the whole cache
            previews[key] = hit
        log.info(
            "preview %s rendered: %d pages, %.0f ms",
            key[:8],
            len(hit.pages),
            (time.perf_counter() - started) * 1000,
        )
        return hit

    async def shared_preview(
        key: str, data: dict, complete: bool, http: HttpRequest
    ) -> Preview:
        # All map operations happen on the event loop without an await between
        # lookup and registration. The enclosing document gate bounds waiters.
        entry = in_flight.get(key)
        if entry is None:
            entry = InFlightPreview(
                asyncio.create_task(compile_preview(key, data, complete))
            )
            in_flight[key] = entry
        entry.waiters += 1
        try:
            while True:
                # asyncio.wait never cancels the shared task when this waiter
                # disconnects or is cancelled.
                done, _ = await asyncio.wait({entry.task}, timeout=0.1)
                if done:
                    return entry.task.result()
                if await http.is_disconnected():
                    raise Aborted()
        finally:
            entry.waiters -= 1
            if entry.waiters == 0:
                del in_flight[key]
                if not entry.task.done():
                    entry.task.cancel()
                # Keep our admission slot until the abandoned compiler has
                # cleaned up. Also retrieve any exception from an abandoned task.
                await asyncio.gather(entry.task, return_exceptions=True)

    async def _run_self_test() -> None:
        app.state.health = await diagnostics.run(settings, gate=gate)

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

    # No interactive API docs or schema: they load scripts from a CDN, which the CSP forbids, and a
    # public site has no need to advertise its API.
    app = FastAPI(
        title="Manuscript Discovery",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(LibraryUnavailable)
    async def unavailable(_, exc: LibraryUnavailable):
        log.warning("Library unavailable: %s", exc)
        return JSONResponse({"detail": "Library unavailable"}, status_code=503)

    @app.exception_handler(Busy)
    async def busy(_, exc: Busy):
        return JSONResponse(
            {"detail": "The server is busy typesetting. Try again in a moment."},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    root = settings.static_dir or assets.serving_root(Path(__file__).parent / "static")
    index = root / "index.html"
    app.add_middleware(
        SecurityHeaders,
        csp=content_security_policy(
            index.read_text("utf-8") if index.is_file() else ""
        ),
    )

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """Liveness: the process is up and the event loop is turning."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        """Readiness: it can actually serve passages (a library with translations, and Typst)."""
        problems = []
        if not shutil.which(settings.typst_bin):
            problems.append("Typst not found")
        try:
            translations = await run_in_threadpool(library.count)
            if translations == 0:
                problems.append("the library has no translations")
        except LibraryUnavailable as e:
            translations = 0
            log.warning("Library unavailable: %s", e)
            problems.append("Library unavailable; run manuscript-discovery ingest")
        return JSONResponse(
            {"ready": not problems, "translations": translations, "problems": problems},
            status_code=503 if problems else 200,
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(
            status_code=204, headers={"Cache-Control": "public, max-age=86400"}
        )

    @app.get("/api/health")
    def health():
        """Version, Typst version, and whether CJK text can be drawn in previews (still checking at first)."""
        return {"version": __version__, **(app.state.health or {"status": "checking"})}

    @app.get("/api/translations")
    def search(
        q: Annotated[str | None, Query(max_length=100)] = None,
        lang: Annotated[str | None, Query(max_length=8)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
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
        async with document_gate:
            if await http.is_disconnected():
                return Response(status_code=499)
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
                    [data, doc.complete, settings.preview_ppi, settings.preview_pages],
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()[:32]
            hit = previews.get(key)
            if hit is None:
                try:
                    hit = await shared_preview(key, data, doc.complete, http)
                except Aborted:
                    log.info("preview %s abandoned: client gone", key[:8])
                    return Response(status_code=499)
                except TypesetError as e:
                    raise HTTPException(500, str(e)) from None
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
        async with document_gate:
            if await http.is_disconnected():
                return Response(status_code=499)
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

    if index.is_file() and not (root / "styles.css").is_file():
        log.warning(
            "styles.css is missing, so the UI will be unstyled: run `manuscript-discovery build-assets`"
        )

    # Last, so every API route above wins; this serves the UI at "/".
    log.info(
        "manuscript-discovery %s: serving the UI from %s%s",
        __version__,
        root,
        " (unminified source: run `manuscript-discovery build-assets`)"
        if root.name != "dist"
        else "",
    )
    app.mount("/", Static(directory=root, html=True), name="ui")
    return app

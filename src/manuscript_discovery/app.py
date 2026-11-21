from __future__ import annotations

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from importlib import resources
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from .document import Request, SelectionError, build_document
from .library import Library, LibraryUnavailable, Translation, UnknownTranslation
from .settings import Settings
from .typeset import TypesetError, render_pdf

log = logging.getLogger(__name__)
TranslationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]


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
    paragraphs: bool = True
    poetry: bool = True
    line_numbers: bool = True
    notes: bool = True
    colophon: bool = True
    download: bool = False


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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not shutil.which(settings.typst_bin):
            log.error("Typst not found (%s): PDF output will fail", settings.typst_bin)
        if not settings.db_path.exists():
            log.warning(
                "No library at %s yet; run `manuscript-discovery ingest`",
                settings.db_path,
            )
        yield
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

    @app.middleware("http")
    async def secure_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        page = resources.files("manuscript_discovery").joinpath("static/index.html")
        return FileResponse(str(page), media_type="text/html; charset=utf-8")

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

    @app.get("/api/render")
    async def render(q: Annotated[RenderQuery, Query()]):
        req = Request(
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
            q.colophon,
        )
        try:
            doc = await run_in_threadpool(
                build_document, library, req, settings.max_verses
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
            pdf = await render_pdf(doc.typst_data(), settings, gate)
        except TypesetError as e:
            raise HTTPException(500, str(e)) from None
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{disposition}; filename="{doc.filename}.pdf"'
            },
        )

    return app

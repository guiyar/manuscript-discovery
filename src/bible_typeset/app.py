from __future__ import annotations

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from importlib import resources
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .document import PAPERS, Request, SelectionError, build_document
from .library import Library
from .settings import Settings
from .typeset import TypesetError, render_pdf

log = logging.getLogger(__name__)


class RenderQuery(BaseModel):
    text: list[str] = Field(
        min_length=1, max_length=2, description="1 text, or 2 for parallel"
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
    label: bool = True
    download: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    library = Library(settings.data_dir, settings.texts_config)
    gate = asyncio.Semaphore(settings.max_concurrent)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not shutil.which(settings.typst_bin):
            log.error("Typst not found (%s): PDF output will fail", settings.typst_bin)
        asyncio.create_task(
            run_in_threadpool(library.warm)
        )  # parse texts in the background
        yield

    app = FastAPI(
        title="Scripture typesetter",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def secure_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        page = resources.files("bible_typeset").joinpath("static/index.html")
        return FileResponse(str(page), media_type="text/html; charset=utf-8")

    @app.get("/api/texts")
    def list_texts():
        return [
            {"id": t.id, "name": t.name, "lang": t.lang} for t in library.texts.values()
        ]

    @app.get("/api/texts/{text_id}/outline")
    async def outline(text_id: str):
        if text_id not in library.texts:
            raise HTTPException(404, "Unknown text")
        loaded = await run_in_threadpool(library.get, text_id)
        return [
            {"code": b.code, "name": b.name, "verses": b.verses}
            for b in loaded.outline.values()
        ]

    @app.get("/api/render")
    async def render(q: Annotated[RenderQuery, Query()]):
        req = Request(
            q.text, q.book, q.c1, q.v1, q.c2, q.v2, q.paper, q.size, q.title, q.label
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

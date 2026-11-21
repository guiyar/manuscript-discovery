import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration, read from ``MANUSCRIPT_*`` environment variables and validated at startup:
    a bad value stops the app with a clear message instead of misbehaving later."""

    model_config = SettingsConfigDict(env_prefix="MANUSCRIPT_")

    db_path: Path = Path("library.sqlite")
    font_dir: Path | None = None  # if set, ONLY these fonts are used (reproducible)
    static_dir: Path | None = (
        None  # default: the minified build if present, else the readable source
    )
    typst_bin: str = "typst"
    max_verses: int = Field(3000, ge=1, le=10_000)  # largest selection accepted
    max_concurrent: int = Field(
        default_factory=lambda: os.cpu_count() or 1, ge=1
    )  # Typst is CPU-bound: one per core
    max_waiting: int = Field(
        16, ge=0
    )  # renders allowed to queue for a slot; more are refused with 503
    timeout_s: float = Field(
        30.0, gt=0, le=300
    )  # one render; keep the proxy's read timeout above this
    preview_pages: int = Field(6, ge=1, le=20)  # pages shown in the live preview
    preview_ppi: int = Field(
        96, ge=48, le=200
    )  # screen resolution; the PDF is the print-quality output
    preview_cache_mb: float = Field(64, gt=0)  # rendered previews kept in memory
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    trusted_proxies: str = "127.0.0.1"  # who may set X-Forwarded-For/-Proto; "*" only if nothing else can reach the port
    log_level: Literal["debug", "info", "warning", "error"] = "info"

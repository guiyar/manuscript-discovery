import os
from pathlib import Path

from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration, read from ``MANUSCRIPT_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="MANUSCRIPT_")

    db_path: Path = Path("library.sqlite")
    font_dir: Path | None = None  # if set, ONLY these fonts are used (reproducible)
    static_dir: Path | None = (
        None  # default: the minified build if present, else the readable source
    )
    typst_bin: str = "typst"
    max_verses: int = 3000  # largest selection accepted
    max_concurrent: int = Field(
        default_factory=lambda: os.cpu_count() or 1
    )  # Typst is CPU-bound: one per core
    timeout_s: float = 60.0
    preview_pages: int = 6  # pages shown in the live preview
    preview_ppi: int = 96  # screen resolution; the PDF is the print-quality output
    preview_cache_mb: float = 64  # rendered previews kept in memory
    host: str = "127.0.0.1"
    port: int = 8000

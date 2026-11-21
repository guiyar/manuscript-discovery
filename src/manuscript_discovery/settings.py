from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration, read from ``MANUSCRIPT_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="MANUSCRIPT_")

    db_path: Path = Path("library.sqlite")
    font_dir: Path | None = None  # if set, ONLY these fonts are used (reproducible)
    typst_bin: str = "typst"
    max_verses: int = 3000  # largest selection accepted
    max_concurrent: int = 4  # simultaneous Typst processes
    timeout_s: float = 60.0
    host: str = "127.0.0.1"
    port: int = 8000

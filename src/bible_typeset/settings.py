from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration, read from ``BIBLE_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="BIBLE_")

    data_dir: Path = Path("data")  # folder holding eBible ``*_usfx.zip`` files
    texts_config: Path | None = None  # optional replacement for the bundled texts.toml
    font_dir: Path | None = None  # if set, ONLY these fonts are used (reproducible)
    typst_bin: str = "typst"
    max_verses: int = 3000  # largest selection accepted
    max_concurrent: int = 4  # simultaneous Typst processes
    timeout_s: float = 60.0
    host: str = "127.0.0.1"
    port: int = 8000

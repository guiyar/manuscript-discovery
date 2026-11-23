import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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
    unix_socket: Path | None = (
        None  # listen here instead of host:port; created with mode 0660 (see listen.py)
    )
    trusted_proxies: str | None = (
        None  # who may set X-Forwarded-For/-Proto; see forwarded_allow_ips
    )
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @field_validator("unix_socket")
    @classmethod
    def _socket_path_is_absolute(cls, path: Path | None) -> Path | None:
        if path is not None and not path.is_absolute():
            raise ValueError("must be an absolute path")
        return path

    @property
    def forwarded_allow_ips(self) -> str:
        """Whose X-Forwarded-* headers to believe.

        Over TCP only a named proxy (default: this machine). On a Unix socket a peer has no address
        to compare, and the socket's file permissions already decide who may connect, so the
        headers are trusted by default; set MANUSCRIPT_TRUSTED_PROXIES to override either way.
        """
        if self.trusted_proxies is not None:
            return self.trusted_proxies
        return "*" if self.unix_socket else "127.0.0.1"

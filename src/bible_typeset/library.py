"""Catalogue of available texts and lazy, cached loading of their contents."""

from __future__ import annotations

import logging
import threading
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .books import book_name, book_sort_key
from .usfx import Piece, load_usfx_zip

log = logging.getLogger(__name__)

_LANG_GUESS = {
    "eng": "en",
    "ind": "id",
    "cmn": "zh",
    "zho": "zh",
    "grc": "el",
    "ell": "el",
    "deu": "de",
    "fra": "fr",
    "spa": "es",
    "por": "pt",
    "ita": "it",
    "rus": "ru",
    "nld": "nl",
    "pol": "pl",
    "swe": "sv",
    "heb": "he",
}


@dataclass(frozen=True, slots=True)
class TextInfo:
    id: str
    name: str
    lang: str
    region: str | None
    font: tuple[str, ...]
    justify: bool
    hyphenate: bool
    cjk: bool
    path: Path

    @property
    def joiner(self) -> str:
        """Separator between consecutive verses that share a paragraph."""
        return "" if self.cjk else " "


@dataclass(slots=True)
class BookOutline:
    code: str
    name: str
    verses: list[int]  # verses[i] = highest verse number in chapter i + 1


@dataclass(slots=True)
class LoadedText:
    books: dict[str, list[Piece]]
    outline: dict[str, BookOutline] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for code in sorted(self.books, key=book_sort_key):
            last: dict[int, int] = {}
            for p in self.books[code]:
                last[p.chapter] = max(last.get(p.chapter, 0), p.end)
            if last:
                self.outline[code] = BookOutline(
                    code,
                    book_name(code),
                    [last.get(c, 0) for c in range(1, max(last) + 1)],
                )


def _load_config(path: Path | None) -> dict:
    if path:
        return tomllib.loads(path.read_text("utf-8"))
    return tomllib.loads(
        resources.files("bible_typeset").joinpath("texts.toml").read_text("utf-8")
    )


class Library:
    def __init__(self, data_dir: Path, config_path: Path | None = None) -> None:
        cfg = _load_config(config_path)
        defaults, specific = cfg.get("defaults", {}), cfg.get("texts", {})
        self.texts: dict[str, TextInfo] = {}
        for zip_path in sorted(Path(data_dir).glob("*_usfx.zip")):
            tid = zip_path.name.removesuffix("_usfx.zip")
            c = {**defaults, **specific.get(tid, {})}
            guess = _LANG_GUESS.get(tid[:3].lower(), tid[:3].lower())
            self.texts[tid] = TextInfo(
                id=tid,
                name=c.get("name", tid),
                lang=specific.get(tid, {}).get("lang") or guess,
                region=c.get("region"),
                font=tuple(c.get("font", ["Libertinus Serif"])),
                justify=bool(c.get("justify", True)),
                hyphenate=bool(c.get("hyphenate", True)),
                cjk=bool(c.get("cjk", False)),
                path=zip_path,
            )
        if not self.texts:
            log.warning("No *_usfx.zip files found in %s", data_dir)
        self._loaded: dict[str, LoadedText] = {}
        self._lock = threading.Lock()

    def get(self, text_id: str) -> LoadedText:
        """Parse a text on first use (seconds for a whole Bible) and keep it in memory."""
        with self._lock:
            if text_id not in self._loaded:
                log.info("Loading %s", text_id)
                self._loaded[text_id] = LoadedText(
                    load_usfx_zip(self.texts[text_id].path)
                )
            return self._loaded[text_id]

    def warm(self) -> None:
        for tid in self.texts:
            self.get(tid)


def select(pieces: list[Piece], c1: int, v1: int, c2: int, v2: int) -> list[Piece]:
    """Pieces whose verse range overlaps (c1:v1)..(c2:v2), inclusive, in document order."""
    lo, hi = (c1, v1), (c2, v2)
    return [
        p for p in pieces if (p.chapter, p.end) >= lo and (p.chapter, p.start) <= hi
    ]

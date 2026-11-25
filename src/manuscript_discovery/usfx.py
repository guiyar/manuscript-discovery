"""Parse eBible.org USFX (XML) into paragraph-aware, verse-addressable pieces.

A *piece* is the part of one verse that lies inside one paragraph or line of poetry. A
paragraph holding several verses becomes several pieces sharing a ``par`` id, so selecting a
verse range is a filter and rebuilding paragraphs is a group-by.

Only text that is part of the scripture is kept. Headings, footnotes, cross-references,
descriptive titles and blank-line markers are editorial additions and are left out.
"""

from __future__ import annotations

import re
import zipfile
from typing import IO, NamedTuple
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET  # hardened against entity-expansion attacks

_MAX_USFX_BYTES = 64 * 1024 * 1024
_MAX_XML_DEPTH = 128
_MAX_XML_ELEMENTS = 1_000_000


class Piece(NamedTuple):
    par: int  # paragraph id, unique within a book
    kind: str  # "p" = prose paragraph, "q" = line of poetry or list
    level: int  # indent level for "q" lines (0 = flush left)
    chapter: int
    start: int  # first verse covered (a bridge such as "3-4" has end > start)
    end: int
    text: str


class Parsed(NamedTuple):
    language_code: str | None  # <languageCode>, e.g. "eng"
    book_names: dict[str, str]  # code -> short name, from the book's own <toc>/<h>
    books: dict[str, list[Piece]]


# Real eBible files carry the paragraph style in ``style``; ``sfm`` is accepted as a fallback.
_PROSE = re.compile(r"^(p|m|mi|nb|pi\d?|pc|pr|pm|pmo|pmc|pmr|cls)$")
_LINES = re.compile(r"^(q\d?|qr|qc|qm\d?|li\d?|lim\d?|lh|lf)$")

# Elements whose content is never scripture text, wherever they occur.
_SKIP = frozenset(
    "f fe x fig ref s s1 s2 s3 s4 ms mr r sr d sp cl cd cp ca va vp h toc id mt rem ide "
    "periph ip imt is io iot il qa b".split()
)
_VERSE_ID = re.compile(r"(\d+)(?:\D+(\d+))?")


def _clean(text: str) -> str:
    return " ".join(text.split())


def _classify(el: Element) -> tuple[str, int] | None:
    style = el.get("style") or el.get("sfm") or {"q": "q", "li": "li"}.get(el.tag, "p")
    digits = re.search(r"\d", style)
    n = int(digits.group()) if digits else int(el.get("level") or 1)
    if _PROSE.match(style):
        return "p", 0
    if _LINES.match(style):
        if style.startswith("li"):
            return "q", max(n - 1, 0)
        if style in ("lh", "lf"):
            return "q", 0
        return "q", {"qr": 3, "qc": 2}.get(style, n)
    return None


class _Walker:
    def __init__(self) -> None:
        self.pieces: list[Piece] = []
        self.chapter = 0
        self.verse: tuple[int, int] | None = None
        self.par = -1
        self.kind, self.level = "p", 0
        self.buf: list[str] = []

    def run(self, book: Element) -> list[Piece]:
        self._children(book)
        self._flush()
        return self.pieces

    def _flush(self) -> None:
        text = _clean("".join(self.buf))
        self.buf = []
        if text and self.verse and self.chapter:
            self.pieces.append(
                Piece(self.par, self.kind, self.level, self.chapter, *self.verse, text)
            )

    def _children(self, el: Element) -> None:
        if el.text:
            self.buf.append(el.text)
        for child in el:
            self._element(child)
            if child.tail:  # text after a footnote or inline tag still belongs to us
                self.buf.append(child.tail)

    def _element(self, el: Element) -> None:
        tag = el.tag
        if tag == "c":
            self._flush()
            cid = el.get("id") or ""
            self.chapter = int(cid) if cid.isdigit() else 0
            self.verse = None
        elif tag == "v":
            self._flush()
            m = _VERSE_ID.match(el.get("id") or "")
            self.verse = (int(m[1]), int(m[2] or m[1])) if m else None
        elif tag == "ve":
            self._flush()
            self.verse = None
        elif tag in ("p", "q", "li"):
            self._flush()
            cls = _classify(el)
            if cls is None:
                return
            self.par += 1
            self.kind, self.level = cls
            self._children(el)
            self._flush()
        elif tag in _SKIP:
            return
        else:  # inline character styles: w, add, nd, wj, qt, tl, bd, it, ...
            self._children(el)


def _short_name(book: Element) -> str | None:
    """<toc level="2"> is the short name; fall back to the running head <h>, then the long name."""
    toc = {t.get("level"): _clean("".join(t.itertext())) for t in book.findall("toc")}
    h = book.find("h")
    return (
        toc.get("2")
        or (_clean("".join(h.itertext())) if h is not None else None)
        or toc.get("1")
        or None
    )


def parse_usfx(stream: IO[bytes]) -> Parsed:
    names: dict[str, str] = {}
    books: dict[str, list[Piece]] = {}
    language = None
    depth = elements = 0
    for event, el in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            depth += 1
            elements += 1
            if depth > _MAX_XML_DEPTH or elements > _MAX_XML_ELEMENTS:
                raise ValueError("USFX XML exceeds structural limits")
            continue
        depth -= 1
        if el.tag == "languageCode":
            language = (el.text or "").strip() or None
        elif el.tag == "book":
            code = (el.get("id") or "").upper()
            if code:
                if name := _short_name(el):
                    names[code] = name
                books[code] = _Walker().run(el)
            el.clear()
    return Parsed(language, names, books)


def load_usfx(zf: zipfile.ZipFile) -> Parsed:
    xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]
    preferred = [n for n in xml if n.lower().endswith("usfx.xml")]
    if not preferred:
        raise ValueError("no *usfx.xml inside the archive")
    member = zf.getinfo(preferred[0])
    if member.file_size > _MAX_USFX_BYTES:
        raise ValueError("USFX XML exceeds decompressed size limit")
    # ZipExtFile bounds reads to the member's declared size. Keep parsing streaming.
    with zf.open(member) as f:
        return parse_usfx(f)

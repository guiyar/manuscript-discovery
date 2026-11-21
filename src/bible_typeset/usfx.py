"""Parse eBible.org USFX (XML) into paragraph-aware, verse-addressable pieces.

USFX is the XML twin of USFM. Compared with eBible's ``readaloud`` files it keeps
verse boundaries; compared with verse-per-line files it keeps paragraph and
poetry structure, which is what good typesetting needs.

A *piece* is the part of one verse that lies inside one paragraph. A verse that
spans two paragraphs becomes two pieces; a paragraph that holds several verses
becomes several pieces sharing the same ``par`` id. Selecting a verse range is
then a filter, and re-assembling paragraphs is a group-by.
"""

from __future__ import annotations

import re
import zipfile
from typing import IO, NamedTuple
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET  # hardened against entity-expansion attacks


class Piece(NamedTuple):
    par: int  # paragraph id, unique within a book
    kind: str  # "p" = prose paragraph, "q" = line of verse/poetry/list
    level: int  # indent level for "q" lines (0 = flush left)
    chapter: int
    start: int  # first verse covered (verse bridges such as "3-4" have end > start)
    end: int
    text: str


# Paragraph styles that carry scripture text. Everything else (headings, cross-reference
# lines, descriptive titles, introductions, running heads) is deliberately left out.
_PROSE = re.compile(r"^(p|m|mi|nb|pi\d?|pc|pr|pm|pmo|pmc|pmr|cls)$")
_LINES = re.compile(r"^(q\d?|qr|qc|qm\d?|li\d?|lim\d?|lh|lf)$")

# Elements whose content is never scripture text, wherever they occur.
_SKIP = frozenset(
    "f fe x fig ref s s1 s2 s3 s4 ms mr r sr d sp cl cd cp ca va vp h toc id mt rem ide "
    "periph ip imt is io iot il qa b".split()
)
_VERSE_ID = re.compile(r"(\d+)(?:\D+(\d+))?")


def _classify(el: Element) -> tuple[str, int] | None:
    sfm = el.get("sfm") or {"q": "q", "li": "li"}.get(el.tag, "p")
    digits = re.search(r"\d", sfm)
    n = int(digits.group()) if digits else int(el.get("level") or 1)
    if _PROSE.match(sfm):
        return "p", 0
    if _LINES.match(sfm):
        if sfm.startswith("li"):
            return "q", max(n - 1, 0)
        if sfm in ("lh", "lf"):
            return "q", 0
        return "q", {"qr": 3, "qc": 2}.get(sfm, n)
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
        text = " ".join("".join(self.buf).split())
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
            self.chapter = (
                int(el.get("id") or 0) if (el.get("id") or "").isdigit() else 0
            )
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


def parse_usfx(stream: IO[bytes]) -> dict[str, list[Piece]]:
    books: dict[str, list[Piece]] = {}
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag == "book":
            code = (el.get("id") or "").upper()
            if code:
                books[code] = _Walker().run(el)
            el.clear()
    return books


def load_usfx_zip(path) -> dict[str, list[Piece]]:
    """Read ``<id>_usfx.zip`` as published on ebible.org."""
    with zipfile.ZipFile(path) as zf:
        xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml:
            raise ValueError(f"{path}: no XML file inside")
        preferred = [n for n in xml if n.lower().endswith("usfx.xml")]
        with zf.open((preferred or xml)[0]) as f:
            return parse_usfx(f)

"""Turn a verse selection into a renderable document (shared by PDF and plain text)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import groupby

from .books import book_name
from .library import Library, TextInfo, select
from .usfx import Piece

PAPERS = ("a4", "a5", "a6", "us-letter")
_CJK_GAP = re.compile(
    r"(?<=[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef])\s+(?=[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef])"
)


class SelectionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(slots=True)
class Request:
    texts: list[str]
    book: str
    c1: int
    v1: int = 1
    c2: int | None = None  # default: same chapter as c1
    v2: int | None = None  # default: end of chapter c2
    paper: str = "a4"
    size: float = 11.0
    title: str | None = None
    label: bool = True


@dataclass(slots=True)
class Section:
    info: TextInfo
    blocks: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class Document:
    title: str
    subtitle: str | None
    paper: str
    size: float
    sections: list[Section]
    filename: str
    show_labels: bool = True

    def typst_data(self) -> dict:
        parallel = len(self.sections) > 1
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "paper": self.paper,
            "size": self.size,
            "texts": [
                {
                    "font": list(s.info.font),
                    "lang": s.info.lang,
                    "region": s.info.region,
                    "hyphenate": s.info.hyphenate,
                    "justify": s.info.justify,
                    "cjk": s.info.cjk,
                    "label": s.info.name if parallel and self.show_labels else None,
                    "blocks": s.blocks,
                }
                for s in self.sections
            ],
        }

    def plain_text(self) -> str:
        parts = [self.title, ""]
        for i, s in enumerate(self.sections):
            if len(self.sections) > 1:
                parts += [f"[{s.info.name}]", ""]
            for b in s.blocks:
                if b["type"] == "prose":
                    parts.append(b["text"])
                else:
                    parts.extend("    " * ln["level"] + ln["text"] for ln in b["lines"])
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"


def reference(name: str, c1: int, v1: int, c2: int, v2: int, last_verse) -> str:
    """'Ephesians 1', 'Ephesians 1:15–23', 'Ephesians 1:15–2:10', 'Ephesians 1–3'..."""
    whole_start = v1 == 1
    whole_end = v2 == last_verse(c2)
    if c1 == c2:
        if whole_start and whole_end:
            return f"{name} {c1}"
        return f"{name} {c1}:{v1}" + (f"–{v2}" if v2 != v1 else "")
    if whole_start and whole_end:
        return f"{name} {c1}–{c2}"
    return f"{name} {c1}:{v1}–{c2}:{v2}"


def build_blocks(pieces: list[Piece], info: TextInfo) -> list[dict]:
    """Group pieces into paragraphs; merge consecutive verse lines into stanzas."""
    blocks: list[dict] = []
    for _, group in groupby(pieces, key=lambda p: p.par):
        group = list(group)
        text = info.joiner.join(p.text for p in group)
        if info.cjk:
            text = _CJK_GAP.sub("", text)
        first = group[0]
        if first.kind == "p":
            blocks.append({"type": "prose", "text": text})
        else:
            line = {"level": first.level, "text": text}
            if blocks and blocks[-1]["type"] == "poetry":
                blocks[-1]["lines"].append(line)
            else:
                blocks.append({"type": "poetry", "lines": [line]})
    return blocks


def build_document(lib: Library, req: Request, max_verses: int) -> Document:
    for tid in req.texts:
        if tid not in lib.texts:
            raise SelectionError(404, f"Unknown text: {tid}")
    loaded = [lib.get(tid) for tid in req.texts]
    for tid, lt in zip(req.texts, loaded):
        if req.book not in lt.outline:
            raise SelectionError(
                422, f"{lib.texts[tid].name} does not contain {book_name(req.book)}"
            )

    verses = (
        loaded[0].outline[req.book].verses
    )  # the first text defines the coordinates
    n = len(verses)

    def last_verse(c: int) -> int:
        return verses[c - 1]

    c1 = req.c1
    c2 = req.c2 if req.c2 is not None else c1
    if not (1 <= c1 <= n and 1 <= c2 <= n):
        raise SelectionError(422, f"{book_name(req.book)} has {n} chapters")
    v1 = req.v1
    v2 = min(req.v2, last_verse(c2)) if req.v2 is not None else last_verse(c2)
    if v1 > last_verse(c1):
        raise SelectionError(422, f"Chapter {c1} has {last_verse(c1)} verses")
    if (c1, v1) > (c2, v2):
        raise SelectionError(422, "The range ends before it starts")

    sections: list[Section] = []
    total = 0
    for tid, lt in zip(req.texts, loaded):
        info = lib.texts[tid]
        pieces = select(lt.books[req.book], c1, v1, c2, v2)
        if not pieces:
            raise SelectionError(404, f"{info.name} has no verses in this range")
        total = max(total, len({(p.chapter, p.start) for p in pieces}))
        sections.append(Section(info, build_blocks(pieces, info)))
    if total > max_verses:
        raise SelectionError(
            422, f"Selection too large ({total} verses; limit {max_verses})"
        )

    title = req.title or reference(book_name(req.book), c1, v1, c2, v2, last_verse)
    subtitle = sections[0].info.name if len(sections) == 1 and req.label else None
    filename = f"{req.book}_{c1}.{v1}-{c2}.{v2}"
    return Document(title, subtitle, req.paper, req.size, sections, filename, req.label)

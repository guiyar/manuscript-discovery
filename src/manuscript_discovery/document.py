"""Turn a verse selection into a renderable document (shared by PDF and plain text)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .books import book_name
from .library import BookOutline, Library, Translation, UnknownBook, UnknownTranslation
from .typography import Typography, typography_for
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
    translations: list[str]
    book: str
    c1: int
    v1: int = 1
    c2: int | None = None  # default: same chapter as c1
    v2: int | None = None  # default: end of chapter c2
    paper: str = "a4"
    size: float = 11.0
    title: str | None = None
    paragraphs: bool = (
        False  # keep paragraph breaks the source marks (off: continuous prose)
    )
    poetry: bool = True  # keep poetry lines the source marks
    line_numbers: bool = True  # per-page line numbers (the first text, when parallel)
    notes: bool = True  # wide margins and open line spacing for study notes
    line_spacing: str = "1.5"  # with notes: "1.5" or "2" (double) lines
    colophon: bool = True  # copyright and licence notice after each text


@dataclass(slots=True)
class Section:
    translation: Translation
    typography: Typography
    blocks: list[dict]
    cut: bool = False  # preview only: the text was truncated here


@dataclass(slots=True)
class Document:
    title: str
    request: Request
    sections: list[Section]
    filename: str

    @property
    def complete(self) -> bool:
        return not any(s.cut for s in self.sections)

    def preview_chars(self, pages: int) -> int:
        """Generous estimate of how much text fills `pages` pages with these settings, so a cut
        preview never shows fewer pages than asked for but layout cost stays bounded."""
        r = self.request
        area = {"a4": 1.0, "a5": 0.5, "a6": 0.25, "us-letter": 1.03}[r.paper]
        per_page = (
            4400 * area * (11 / r.size) ** 2
        )  # characters per page, plain layout, 11 pt A4
        per_page *= (
            0.45 * 1.5 / float(r.line_spacing) if r.notes else 1
        )  # wide margins, open spacing
        per_page *= (
            0.5 if len(self.sections) > 1 else 1
        )  # parallel: each text has half the width
        return int(per_page * pages * 1.3)

    def truncated(self, max_chars: int) -> "Document":
        """Keep roughly the first max_chars of each text, cutting inside a block at a word
        boundary if need be (continuous prose is a single huge block). A preview shows only the
        first few pages and page layout is the expensive part, so this bounds the cost of a
        preview however large the selection. A cut text gets no colophon: it would sit mid-text."""
        sections = []
        for s in self.sections:
            kept, size, cut = [], 0, False
            limit = max_chars * (
                0.4 if s.typography.cjk else 1
            )  # full-width characters fill a page sooner
            for b in s.blocks:
                if size >= limit:
                    cut = True
                    break
                clipped, was_cut = _clip(b, int(limit - size))
                kept.append(clipped)
                size += _weight(clipped)
                if was_cut:
                    cut = True
                    break
            sections.append(replace(s, blocks=kept, cut=cut))
        return replace(self, sections=sections)

    def _colophon(self, s: Section) -> dict | None:
        t, m = s.translation, s.translation.meta
        if s.cut or not self.request.colophon or not (m.short_notice or m.copyright):
            return None
        return {
            "name": t.name,
            "abbreviation": t.abbreviation,
            "notice": m.short_notice,
            "statement": m.statement_paragraphs,
        }

    @property
    def leading_em(self) -> float:
        """Gap between lines in em. Typst measures from the baseline to the next line's cap
        height (about 0.66 em), so a line pitch of 1.5x or 2x a 1.2 em single line needs these."""
        return (
            {"1.5": 1.15, "2": 1.75}[self.request.line_spacing]
            if self.request.notes
            else 0.68
        )

    def typst_data(self) -> dict:
        r, parallel = self.request, len(self.sections) > 1
        return {
            "title": self.title,
            "paper": r.paper,
            "size": r.size,
            "notes": r.notes,
            "leading": self.leading_em,
            "texts": [
                {
                    "font": list(s.typography.font),
                    "lang": s.typography.lang,
                    "region": s.typography.region,
                    "dir": s.typography.dir,
                    "hyphenate": s.typography.hyphenate,
                    "justify": s.typography.justify,
                    "cjk": s.typography.cjk,
                    # Typst counts every numbered line on a page, whichever column it is in, and draws
                    # all the numbers in one margin. So only the first text is numbered: its lines
                    # then number cleanly, whatever the other column's line height.
                    "numbered": r.line_numbers and i == 0,
                    "heading": s.translation.abbreviation if parallel else None,
                    "blocks": s.blocks,
                    "colophon": self._colophon(s),
                }
                for i, s in enumerate(self.sections)
            ],
        }

    def plain_text(self) -> str:
        parts = [self.title, ""]
        for s in self.sections:
            if len(self.sections) > 1:
                parts += [f"[{s.translation.abbreviation}]", ""]
            for b in s.blocks:
                if b["type"] == "prose":
                    parts.append(b["text"])
                else:
                    parts.extend("    " * ln["level"] + ln["text"] for ln in b["lines"])
                parts.append("")
            if c := self._colophon(s):
                parts += ["—", f"{c['name']} ({c['abbreviation']})"]
                parts += [x for x in (c["notice"], *c["statement"]) if x]
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"


def _weight(block: dict) -> int:
    return (
        sum(len(x["text"]) for x in block["lines"])
        if block["type"] == "poetry"
        else len(block["text"])
    )


def _clip(block: dict, room: int) -> tuple[dict, bool]:
    """The block cut to about `room` characters, and whether anything was dropped."""
    if block["type"] == "prose":
        text = block["text"]
        if len(text) <= room:
            return block, False
        return {**block, "text": text[:room].rsplit(" ", 1)[0] or text[:room]}, True
    lines, used = [], 0
    for line in block["lines"]:
        if used >= room:
            return {**block, "lines": lines}, True
        lines.append(line)
        used += len(line["text"])
    return block, False


def reference(name: str, c1: int, v1: int, c2: int, v2: int, last_verse) -> str:
    """'Ephesians 1', 'Ephesians 1:15–23', 'Ephesians 1:15–2:10', 'Ephesians 1–3'..."""
    whole = v1 == 1 and v2 == last_verse(c2)
    if c1 == c2:
        if whole:
            return f"{name} {c1}"
        return f"{name} {c1}:{v1}" + (f"–{v2}" if v2 != v1 else "")
    return f"{name} {c1}–{c2}" if whole else f"{name} {c1}:{v1}–{c2}:{v2}"


def resolve_range(
    t: Translation, ob: BookOutline, req: Request
) -> tuple[int, int, int, int]:
    """Check the requested range against this translation. Never alters it: a range the
    translation cannot satisfy is an error that names the translation and the shortfall."""
    n = len(ob.verses)
    c1, v1 = req.c1, req.v1
    c2 = req.c2 if req.c2 is not None else c1
    for c in (c1, c2):
        if c > n:
            raise SelectionError(
                422, f"{t.name} has {n} chapters of {ob.name}, not {c}"
            )
    v2 = req.v2 if req.v2 is not None else ob.verses[c2 - 1]
    for c, v in ((c1, v1), (c2, v2)):
        if v > ob.verses[c - 1]:
            raise SelectionError(
                422, f"{t.name}: {ob.name} {c} has {ob.verses[c - 1]} verses, not {v}"
            )
    if (c1, v1) > (c2, v2):
        raise SelectionError(422, "The range ends before it starts")
    return c1, v1, c2, v2


def build_blocks(
    pieces: list[Piece], ty: Typography, *, paragraphs: bool, poetry: bool
) -> list[dict]:
    """Prose paragraphs and poetry stanzas, as far as the toggles and the source's own
    markup allow. Turning a toggle off only ever merges: nothing is invented."""
    blocks: list[dict] = []
    prev: Piece | None = None
    for p in pieces:
        same_par = prev is not None and p.par == prev.par
        if p.kind == "q" and poetry:
            line = {"level": p.level, "text": p.text}
            if same_par:
                blocks[-1]["lines"][-1]["text"] += ty.joiner + p.text
            elif blocks and blocks[-1]["type"] == "poetry":
                blocks[-1]["lines"].append(line)
            else:
                blocks.append({"type": "poetry", "lines": [line]})
        else:
            runs_on = (
                same_par
                or not paragraphs
                or (p.kind == "q" and prev is not None and prev.kind == "q")
            )
            if blocks and blocks[-1]["type"] == "prose" and runs_on:
                blocks[-1]["text"] += ty.joiner + p.text
            else:
                blocks.append({"type": "prose", "text": p.text})
        prev = p
    if ty.cjk:
        for b in blocks:
            for item in b["lines"] if b["type"] == "poetry" else [b]:
                item["text"] = _CJK_GAP.sub("", item["text"])
    return blocks


def build_document(lib: Library, req: Request, max_verses: int) -> Document:
    sections: list[Section] = []
    primary: tuple[str, tuple[int, int, int, int], BookOutline] | None = None
    for tid in req.translations:
        try:
            t = lib.get(tid)
            ob = next((b for b in lib.outline(tid) if b.code == req.book), None)
        except UnknownTranslation:
            raise SelectionError(404, f"Unknown translation: {tid}") from None
        if ob is None:
            raise SelectionError(
                422, f"{t.name} does not contain {book_name(req.book)}"
            )
        c1, v1, c2, v2 = resolve_range(t, ob, req)
        try:
            pieces = lib.pieces(tid, req.book, (c1, v1), (c2, v2))
        except (
            UnknownBook
        ):  # cannot happen after the outline check; keeps the contract honest
            raise SelectionError(
                422, f"{t.name} does not contain {book_name(req.book)}"
            ) from None
        if not pieces:
            raise SelectionError(404, f"{t.name} has no text in this range")
        if len({(p.chapter, p.start) for p in pieces}) > max_verses:
            raise SelectionError(
                422, f"Selection too large (limit {max_verses} verses)"
            )
        ty = typography_for(t.meta)
        sections.append(
            Section(
                t,
                ty,
                build_blocks(pieces, ty, paragraphs=req.paragraphs, poetry=req.poetry),
            )
        )
        if primary is None:
            primary = (t.id, (c1, v1, c2, v2), ob)

    _, (c1, v1, c2, v2), ob = primary
    title = req.title or reference(ob.name, c1, v1, c2, v2, lambda c: ob.verses[c - 1])
    return Document(title, req, sections, f"{req.book}_{c1}.{v1}-{c2}.{v2}")

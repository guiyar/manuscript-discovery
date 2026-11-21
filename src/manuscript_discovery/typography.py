"""Typesetting settings derived from a translation's metadata (no hand-kept per-text list)."""

from __future__ import annotations

from dataclasses import dataclass

import pycountry

from .metadata import Metadata

# Typst picks hyphenation patterns by ISO 639-1 code and ignores three-letter ones. Where a
# language has no 639-1 code of its own, point it at the closest one Typst knows:
#   cmn  Mandarin: no 639-1 code, but Typst's Chinese line-breaking rules are keyed on "zh"
#   grc  Ancient Greek: no patterns exist, but the Greek ones hyphenate polytonic text well
_TYPST_LANG = {"cmn": "zh", "grc": "el"}
_CJK = {"zh", "ja", "ko"}
_TRADITIONAL_REGIONS = {"tw", "hk", "mo"}
_LATIN_SERIF = (
    "Libertinus Serif"  # Latin, Greek, Cyrillic; other scripts fall back per glyph
)


@dataclass(frozen=True, slots=True)
class Typography:
    lang: str
    region: str | None
    dir: str  # "ltr" | "rtl"
    font: tuple[str, ...]
    cjk: bool
    hyphenate: bool
    justify: bool

    @property
    def joiner(self) -> str:
        """Separator between consecutive verses that share a paragraph."""
        return "" if self.cjk else " "


def _iso1(iso3: str | None) -> str:
    if not iso3:
        return "en"
    if iso3 in _TYPST_LANG:
        return _TYPST_LANG[iso3]
    found = pycountry.languages.get(alpha_3=iso3)
    return getattr(found, "alpha_2", None) or iso3


def _cjk_font(lang: str, region: str | None, script: str | None) -> str:
    if lang == "ja":
        return "Noto Serif CJK JP"
    if lang == "ko":
        return "Noto Serif CJK KR"
    traditional = (region in _TRADITIONAL_REGIONS) or "tradition" in (
        script or ""
    ).lower()
    return "Noto Serif CJK TC" if traditional else "Noto Serif CJK SC"


def typography_for(meta: Metadata) -> Typography:
    lang = _iso1(meta.language)
    region = meta.country.lower() if meta.country and len(meta.country) == 2 else None
    cjk = lang in _CJK
    # CJK font first: otherwise the Latin font's narrow punctuation wins over full-width forms.
    font = (
        (_cjk_font(lang, region, meta.script), _LATIN_SERIF) if cjk else (_LATIN_SERIF,)
    )
    return Typography(
        lang=lang,
        region=region,
        dir="rtl" if (meta.direction or "").upper() == "RTL" else "ltr",
        font=font,
        cjk=cjk,
        hyphenate=not cjk,
        justify=True,
    )

"""Startup self-test: can this Typst and font set really draw CJK text in PNG previews?

Why it exists: Typst before 0.15 draws empty boxes in PNG export for the variable Noto Serif CJK
font that nixpkgs ships, while the same document exports to PDF perfectly. Nothing errors, so the
failure is silent. The test renders two different characters per CJK family; when the glyphs are
missing both come out as the same "no glyph" box, so identical images mean failure.
"""

from __future__ import annotations

import asyncio
import logging

from .settings import Settings
from .typeset import TypesetError, _compile, finish
from .typography import CJK_FONTS

log = logging.getLogger(__name__)
_SAMPLES = ("我", "帝")  # any two different, common characters


def _source() -> str:
    pages = []
    for family in CJK_FONTS:
        for ch in _SAMPLES:
            pages.append(
                f"#set page(width: 2cm, height: 2cm, margin: 2mm)\n"
                f'#set text(size: 24pt, font: ("{family}", "Libertinus Serif"))\n'
                f"#align(center + horizon)[{ch}]"
            )
    return "\n#pagebreak()\n".join(pages)


async def _version(settings: Settings) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.typst_bin,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await finish(proc, 10)
        return out.decode().strip() or None
    except (OSError, TypesetError):
        return None


async def run(settings: Settings) -> dict:
    version = await _version(settings)
    if version is None:
        return {"typst": None, "cjk_png": {}, "ok": False}
    try:
        pages = await _compile(
            {},
            settings,
            asyncio.Semaphore(1),
            ["--format", "png", "--ppi", "48"],
            "out-{0p}.png",
            lambda w: [f.read_bytes() for f in sorted(w.glob("out-*.png"))],
            None,
            source=_source(),
        )
    except TypesetError:
        return {"typst": version, "cjk_png": {}, "ok": False}
    width = len(_SAMPLES)
    cjk = {
        family: pages[i * width] != pages[i * width + 1]
        for i, family in enumerate(CJK_FONTS)
    }
    result = {"typst": version, "cjk_png": cjk, "ok": all(cjk.values())}
    if not result["ok"]:
        broken = ", ".join(f for f, ok in cjk.items() if not ok)
        log.error(
            "CJK text will show as empty boxes in PNG previews (%s). %s cannot draw these fonts: "
            "older Typst with a variable Noto Serif CJK is a known cause. Use Typst 0.15 or newer, or a "
            "static Noto Serif CJK / Source Han Serif font (the PDF output is unaffected).",
            broken,
            version,
        )
    return result

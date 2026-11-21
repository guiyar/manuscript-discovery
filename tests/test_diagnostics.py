import asyncio
import logging
import os
import shutil

import pytest

from manuscript_discovery import diagnostics
from manuscript_discovery.settings import Settings

HAS_TYPST = shutil.which(Settings().typst_bin) is not None
pytestmark = pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")


def test_fonts_that_cannot_draw_cjk_are_detected_and_explained(tmp_path, caplog):
    """The silent failure seen in practice: no usable CJK glyphs means identical empty boxes."""
    with caplog.at_level(logging.ERROR, logger="manuscript_discovery.diagnostics"):
        result = asyncio.run(
            diagnostics.run(Settings(font_dir=tmp_path))
        )  # an empty font folder
    assert result["ok"] is False and not any(result["cjk_png"].values())
    assert result["typst"].startswith("typst ")
    assert "empty boxes" in caplog.text and "0.15" in caplog.text


def test_a_missing_typst_is_reported_not_raised():
    assert asyncio.run(diagnostics.run(Settings(typst_bin="/nonexistent/typst"))) == {
        "typst": None,
        "cjk_png": {},
        "ok": False,
    }


@pytest.mark.skipif(
    not os.environ.get("MANUSCRIPT_EXPECT_CJK"),
    reason="set MANUSCRIPT_EXPECT_CJK=1 where the font set must cover CJK (the Nix check does)",
)
def test_the_configured_fonts_really_draw_cjk_in_png():
    result = asyncio.run(diagnostics.run(Settings()))
    assert result["ok"], result

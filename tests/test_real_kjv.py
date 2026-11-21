"""Smoke test against a real eBible zip. Set MANUSCRIPT_TEST_KJV=/path/to/eng-kjv2006_usfx.zip."""

import os
from pathlib import Path

import pytest

from manuscript_discovery.ingest import ingest_paths
from manuscript_discovery.library import Library

SRC = os.environ.get("MANUSCRIPT_TEST_KJV")
pytestmark = pytest.mark.skipif(
    not SRC or not Path(SRC).exists(), reason="no real KJV zip given"
)


@pytest.fixture(scope="module")
def kjv(tmp_path_factory):
    db = tmp_path_factory.mktemp("real") / "l.sqlite"
    assert ingest_paths([Path(SRC)], db)[:2] == (1, 0)
    lib = Library(db)
    yield lib
    lib.close()


def test_real_file_is_complete_and_clean(kjv):
    books = {b.code: b for b in kjv.outline("eng-kjv2006")}
    assert len(books) == 66 and list(books["EPH"].verses) == [23, 22, 21, 32, 33, 24]
    pieces = {c: kjv.pieces("eng-kjv2006", c, (1, 1), (200, 200)) for c in books}
    assert sum(len(b.verses) for b in books.values()) == 1189
    assert (
        len({(c, p.chapter, p.start) for c, ps in pieces.items() for p in ps}) == 31102
    )
    text = " ".join(p.text for ps in pieces.values() for p in ps)
    assert "Heb." not in text and "H7225" not in text
    assert (
        kjv.pieces("eng-kjv2006", "GEN", (1, 1), (1, 1))[0].text
        == "In the beginning God created the heaven and the earth."
    )


def test_real_metadata(kjv):
    t = kjv.get("eng-kjv2006")
    assert (t.name, t.abbreviation, t.lang) == ("King James Version", "KJV", "eng")
    assert (
        t.meta.short_notice == "Public Domain"
        and t.meta.script == "Latin"
        and t.meta.country == "GB"
    )
    assert any("Letters patent" in p for p in t.meta.statement_paragraphs)

import io

from bible_typeset.usfx import parse_usfx
from conftest import TEXTS, USFX_HEAD, eph


def parse(tid="eng-kjv2006"):
    lang, v = TEXTS[tid]
    return parse_usfx(
        io.BytesIO((USFX_HEAD.format(lang=lang) + eph(v) + "</usfx>").encode())
    )


def test_only_scripture_text_survives():
    alltext = " ".join(p.text for pieces in parse().values() for p in pieces)
    for junk in ("FOOTNOTE", "must not appear", "A Psalm of David"):
        assert junk not in alltext


def test_verses_and_paragraphs():
    eph_ = parse()["EPH"]
    by_verse = {(p.chapter, p.start): p for p in eph_}
    assert by_verse[(1, 3)].par == by_verse[(1, 4)].par  # two verses, one paragraph
    assert by_verse[(1, 2)].par == by_verse[(1, 1)].par
    assert by_verse[(1, 2)].par != by_verse[(1, 3)].par
    assert (
        by_verse[(1, 1)].text == "Paul, an apostle of Jesus Christ"
    )  # footnote stripped, no verse number


def test_verse_bridge_keeps_both_numbers():
    p = [p for p in parse()["EPH"] if p.chapter == 2 and p.start == 2][0]
    assert p.end == 3


def test_poetry_levels_and_stanza_lines():
    lines = parse()["PSA"]
    assert [(p.kind, p.level) for p in lines] == [("q", 1), ("q", 2), ("q", 1)]

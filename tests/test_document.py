import re

import pytest

from manuscript_discovery.document import (
    Request,
    SelectionError,
    build_document,
    reference,
)


def build(lib, translations=("eng-kjv2006",), book="EPH", c1=1, **kw):
    return build_document(lib, Request(list(translations), book, c1, **kw), 1000)


def blocks(doc, i=0):
    return doc.sections[i].blocks


@pytest.mark.parametrize(
    "args,expected",
    [
        ((1, 1, 1, 4), "Ephesians 1"),
        ((1, 2, 1, 3), "Ephesians 1:2–3"),
        ((1, 2, 1, 2), "Ephesians 1:2"),
        ((1, 3, 2, 2), "Ephesians 1:3–2:2"),
        ((1, 1, 2, 3), "Ephesians 1–2"),
    ],
)
def test_reference_title(args, expected):
    assert reference("Ephesians", *args, last_verse=lambda c: [4, 3][c - 1]) == expected


def test_title_uses_the_translations_own_book_name(lib):
    assert build(lib, ("grctr",), c1=1).title == "Ἐφεσίους 1"


def test_defaults_follow_the_sources_own_paragraphs_and_poetry(lib):
    b = blocks(build(lib, c1=1, v1=1, c2=2, v2=3))
    assert (
        [x["text"] for x in b]
        == [
            "Paul, an apostle of Jesus Christ Grace be to you",  # verses 1-2: one source paragraph
            "Blessed be the God According as he hath chosen us",  # verses 3-4: another
            "And you hath he quickened",
            "Wherein in time past ye walked",
        ]
    )


def test_poetry_lines_keep_levels_without_stanza_gaps(lib):
    b = blocks(build(lib, book="PSA", c1=23, v1=1, v2=3))
    assert [x["type"] for x in b] == [
        "poetry",
        "prose",
    ]  # <b/> adds no gap; prose resumes after
    assert b[0]["lines"] == [
        {"level": 1, "text": "The LORD is my shepherd;"},
        {"level": 2, "text": "I shall not want."},
        {"level": 1, "text": "He maketh me to lie down"},
    ]


def test_paragraph_toggle_off_runs_prose_together(lib):
    b = blocks(build(lib, c1=1, v2=None, c2=2, paragraphs=False))
    assert (
        len(b) == 1
        and b[0]["text"].startswith("Paul, an apostle of Jesus Christ Grace")
        and b[0]["text"].endswith("ye walked")
    )


def test_poetry_toggle_off_turns_lines_into_one_paragraph(lib):
    b = blocks(build(lib, book="PSA", c1=23, poetry=False))
    assert [x["type"] for x in b] == ["prose", "prose"]
    assert (
        b[0]["text"]
        == "The LORD is my shepherd; I shall not want. He maketh me to lie down"
    )


def test_both_toggles_off_gives_one_continuous_block(lib):
    assert (
        len(blocks(build(lib, book="PSA", c1=23, paragraphs=False, poetry=False))) == 1
    )


def test_plain_text_has_a_title_but_no_numbers(lib):
    doc = build(lib, c1=1, v1=2, c2=2, v2=1, colophon=False)
    first, *rest = doc.plain_text().splitlines()
    assert first == "Ephesians 1:2–2:1" and not re.search(r"\d", "\n".join(rest))


def test_colophon_has_licence_notice_and_copyright_for_each_text(lib):
    doc = build(lib, ("eng-kjv2006", "grctr"), c1=1)
    kjv, tr = (t["colophon"] for t in doc.typst_data()["texts"])
    assert kjv["notice"] == "Public Domain" and kjv["abbreviation"] == "KJV"
    assert kjv["statement"][-1] == "Courtesy of Crosswire & eBible."
    assert tr["name"] == "Greek Textus Receptus" and tr["statement"] == []
    text = doc.plain_text()
    assert text.count("Public Domain") == 2 and "King James Version (KJV)" in text
    assert all(
        t["colophon"] is None
        for t in build(lib, c1=1, colophon=False).typst_data()["texts"]
    )


def test_no_metadata_means_no_colophon_not_an_error(lib):
    assert build(lib, ("nometa",), c1=1).typst_data()["texts"][0]["colophon"] is None


def test_parallel_headings_use_abbreviations(lib):
    data = build(lib, ("grctr", "eng-kjv2006"), c1=1).typst_data()
    assert [t["heading"] for t in data["texts"]] == ["TR", "KJV"]
    assert build(lib, c1=1).typst_data()["texts"][0]["heading"] is None


def test_cjk_text_gets_no_inserted_spaces(lib):
    b = blocks(build(lib, ("cmn2006",), c1=1, v1=1, v2=2))
    assert b[0]["text"] == "藉着神旨意作基督耶稣使徒的保罗，愿恩惠、平安归与你们。"


# --- the chosen range is never silently changed -------------------------------------------


def err(lib, translations=("eng-kjv2006",), **kw):
    with pytest.raises(SelectionError) as e:
        build(lib, translations, **kw)
    return e.value


def test_translation_too_short_for_the_range_is_named_in_the_error(lib):
    e = err(lib, ("tiny",), c1=2)  # tiny has no chapter 2
    assert (
        e.status == 422
        and e.message == "Tiny Version has 1 chapters of Ephesians, not 2"
    )
    e = err(lib, ("eng-kjv2006",), c1=1, v2=9)
    assert e.message == "King James Version: Ephesians 1 has 4 verses, not 9"


def test_every_translation_in_a_parallel_pair_is_checked(lib):
    assert "Tiny Version" in err(lib, ("eng-kjv2006", "tiny"), c1=1, c2=2).message


def test_missing_book_unknown_translation_and_reversed_range(lib):
    assert (
        err(lib, ("tiny",), book="GEN", c1=1).message
        == "Tiny Version does not contain Genesis"
    )
    assert err(lib, ("nope",), c1=1).status == 404
    assert err(lib, c1=2, v1=2, c2=1, v2=1).status == 422


def test_size_limit(lib):
    with pytest.raises(SelectionError, match="too large"):
        build_document(lib, Request(["eng-kjv2006"], "EPH", 1, c2=2), max_verses=3)

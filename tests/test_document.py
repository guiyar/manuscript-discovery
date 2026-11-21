import re

import pytest

from bible_typeset.document import Request, SelectionError, build_document, reference
from bible_typeset.library import Library, select


@pytest.fixture(scope="module")
def lib(data_dir):
    return Library(data_dir)


def test_all_zips_discovered_with_config(lib):
    assert set(lib.texts) == {"eng-kjv2006", "grctr", "cmn2006"}
    assert lib.texts["grctr"].lang == "el" and lib.texts["cmn2006"].cjk


def test_outline(lib):
    o = lib.get("eng-kjv2006").outline["EPH"]
    assert o.verses == [4, 3] and o.name == "Ephesians"


def test_select_range_across_chapters_and_bridge(lib):
    pieces = lib.get("eng-kjv2006").books["EPH"]
    got = {(p.chapter, p.start) for p in select(pieces, 1, 3, 2, 3)}
    assert got == {(1, 3), (1, 4), (2, 1), (2, 2)}  # bridge 2:2-3 included via verse 3


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
def test_reference(args, expected):
    assert reference("Ephesians", *args, last_verse=lambda c: [4, 3][c - 1]) == expected


def test_plain_text_has_title_but_no_numbers(lib):
    doc = build_document(lib, Request(["eng-kjv2006"], "EPH", 1, 2, 2, 1), 100)
    first, *rest = doc.plain_text().splitlines()
    assert first == "Ephesians 1:2–2:1"
    assert not re.search(r"\d", "\n".join(rest))
    # verses 3 and 4 share a paragraph and are joined; verse 2 closed its own paragraph
    assert (
        "\n\nBlessed be the God According as he hath chosen us\n\n" in doc.plain_text()
    )


def test_poetry_becomes_one_indented_stanza(lib):
    doc = build_document(lib, Request(["eng-kjv2006"], "PSA", 23), 100)
    assert [b["type"] for b in doc.sections[0].blocks] == ["poetry"]
    assert doc.plain_text().splitlines()[2:] == [
        "    The LORD is my shepherd;",
        "        I shall not want.",
        "    He maketh me to lie down",
    ]


def test_cjk_has_no_inserted_spaces(lib):
    doc = build_document(lib, Request(["cmn2006"], "EPH", 1, 1, 1, 2), 100)
    assert (
        doc.sections[0].blocks[0]["text"]
        == "藉着神旨意作基督耶稣使徒的保罗，愿恩惠、平安归与你们。"
    )


def test_parallel_has_two_sections_and_labels(lib):
    doc = build_document(lib, Request(["grctr", "eng-kjv2006"], "EPH", 1), 100)
    data = doc.typst_data()
    assert [t["label"] for t in data["texts"]] == [
        "Greek Textus Receptus",
        "King James Version",
    ]
    assert doc.subtitle is None


@pytest.mark.parametrize(
    "kwargs,status",
    [
        (dict(book="GEN", c1=1), 422),
        (dict(book="EPH", c1=9), 422),
        (dict(book="EPH", c1=1, v1=9), 422),
        (dict(book="EPH", c1=2, v1=2, c2=1, v2=1), 422),
        (dict(texts=["nope"], book="EPH", c1=1), 404),
    ],
)
def test_invalid_selections(lib, kwargs, status):
    kwargs.setdefault("texts", ["eng-kjv2006"])
    with pytest.raises(SelectionError) as e:
        build_document(lib, Request(**kwargs), 100)
    assert e.value.status == status


def test_size_limit(lib):
    with pytest.raises(SelectionError):
        build_document(lib, Request(["eng-kjv2006"], "EPH", 1, c2=2), max_verses=3)

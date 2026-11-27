import io
import zipfile

import pytest

from conftest import EL, EN, usfx
from manuscript_discovery.usfx import load_usfx, parse_usfx


def parse(v=EN, lang="eng"):
    return parse_usfx(io.BytesIO(usfx(lang, v).encode("utf-8")))


def test_bom_language_and_names_come_from_the_file():
    p = parse(EL, "grc")
    assert p.language_code == "grc" and p.book_names == {
        "EPH": "Ἐφεσίους",
        "PSA": "Psalms",
    }


def test_only_scripture_text_survives():
    text = " ".join(x.text for pieces in parse().books.values() for x in pieces)
    for junk in ("FOOTNOTE", "must not appear", "A Psalm of David", "G5485"):
        assert junk not in text
    assert "Grace be to you" in text  # text inside <w s="..."> is kept


def test_verses_and_paragraphs():
    by_verse = {(p.chapter, p.start): p for p in parse().books["EPH"]}
    assert by_verse[(1, 3)].par == by_verse[(1, 4)].par == by_verse[(1, 3)].par
    assert by_verse[(1, 1)].par == by_verse[(1, 2)].par != by_verse[(1, 3)].par
    assert by_verse[(1, 1)].text == "Paul, an apostle of Jesus Christ"


def test_verse_bridge_keeps_both_numbers():
    assert [p.end for p in parse().books["EPH"] if (p.chapter, p.start) == (2, 2)] == [
        3
    ]


def test_poetry_levels_and_prose_after_poetry():
    assert [(p.kind, p.level) for p in parse().books["PSA"]] == [
        ("q", 1),
        ("q", 2),
        ("q", 1),
        ("p", 0),
    ]


def test_zip_without_usfx_is_an_error(tmp_path):
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", "no xml here")
    with zipfile.ZipFile(path) as zf, pytest.raises(ValueError, match="usfx"):
        load_usfx(zf)


def test_oversized_usfx_member_is_rejected(tmp_path, monkeypatch):
    import manuscript_discovery.usfx as parser

    monkeypatch.setattr(parser, "_MAX_USFX_BYTES", 32)
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("x-usfx.xml", "<usfx>" + "x" * 100 + "</usfx>")
    with (
        zipfile.ZipFile(path) as zf,
        pytest.raises(ValueError, match="decompressed size"),
    ):
        load_usfx(zf)


def test_usfx_structure_is_bounded(monkeypatch):
    import manuscript_discovery.usfx as parser

    monkeypatch.setattr(parser, "_MAX_XML_DEPTH", 3)
    with pytest.raises(ValueError, match="structural limits"):
        parse_usfx(io.BytesIO(b"<a><b><c><d/></c></b></a>"))
    monkeypatch.setattr(parser, "_MAX_XML_ELEMENTS", 3)
    with pytest.raises(ValueError, match="structural limits"):
        parse_usfx(io.BytesIO(b"<a><b/><b/><b/></a>"))


def test_oversized_archive_is_rejected_before_hashing(tmp_path, monkeypatch):
    from manuscript_discovery import ingest

    monkeypatch.setattr(ingest, "_MAX_ARCHIVE_BYTES", 32)
    path = tmp_path / "large_usfx.zip"
    path.write_bytes(b"x" * 33)
    with pytest.raises(ValueError, match="compressed size"):
        ingest.read_source(str(path))
    assert ingest.ingest_paths([path], tmp_path / "library.sqlite") == (
        0,
        0,
        ["large"],
    )

import zipfile

from conftest import BOM, PD, dbl
from manuscript_discovery.metadata import Metadata, read_metadata


def meta_for(tmp_path, files: dict[str, str], fallback=None):
    path = tmp_path / "m.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    with zipfile.ZipFile(path) as zf:
        return read_metadata(zf, fallback)


def test_dbl_fields_and_clean_statement(tmp_path):
    m = meta_for(
        tmp_path,
        {
            "x-metadata.xml": dbl(
                "King James Version", "KJV", "eng", "English", "Latin", "LTR", "GB", PD
            ),
            "x-VernacularAdditional.xml": f"{BOM}<a><copyright>Notice here.</copyright></a>",
        },
    )
    assert (m.name, m.abbreviation_local, m.language, m.language_name) == (
        "King James Version",
        "KJV",
        "eng",
        "English",
    )
    assert (m.script, m.direction, m.country, m.notice) == (
        "Latin",
        "LTR",
        "GB",
        "Notice here.",
    )
    assert (
        "<a" not in m.copyright and "Crosswire & eBible." in m.copyright
    )  # markup stripped, entities decoded
    assert m.short_notice == "Public Domain"
    assert m.statement_paragraphs == [
        "Letters patent mean you need permission in the UK.",
        "Courtesy of Crosswire & eBible.",
    ]


def test_long_first_line_falls_back_to_the_one_line_notice():
    m = Metadata(copyright="x" * 200, notice="Short one.")
    assert m.short_notice == "Short one."
    assert Metadata(copyright="x" * 200).short_notice == "x" * 100


def test_missing_files_leave_fields_empty_and_use_fallback_language(tmp_path):
    m = meta_for(tmp_path, {"a_usfx.xml": "<usfx/>"}, fallback="ind")
    assert (
        m.language == "ind"
        and m.name is None
        and m.short_notice is None
        and m.statement_paragraphs == []
    )


def test_unreadable_or_unexpected_xml_is_tolerated(tmp_path):
    assert meta_for(tmp_path, {"a-metadata.xml": "<not xml"}).name is None
    odd = meta_for(
        tmp_path,
        {
            "b-metadata.xml": '<Other xmlns="urn:x"><identification><name>Odd</name></identification></Other>'
        },
    )
    assert odd.name == "Odd" and odd.copyright is None


def test_roundtrips_through_dict_ignoring_unknown_keys():
    m = Metadata(name="N", language="eng")
    from dataclasses import asdict

    assert Metadata.from_dict({**asdict(m), "added_in_a_future_version": 1}) == m


def test_oversized_metadata_is_ignored(tmp_path, monkeypatch):
    import manuscript_discovery.metadata as metadata

    monkeypatch.setattr(metadata, "_MAX_METADATA_BYTES", 64)
    result = meta_for(
        tmp_path,
        {
            "x-metadata.xml": "<a>" + "x" * 100 + "</a>",
            "x-VernacularAdditional.xml": "<a><copyright>Notice</copyright></a>",
        },
        fallback="eng",
    )
    assert result.name is None and result.language == "eng"
    assert result.notice == "Notice"

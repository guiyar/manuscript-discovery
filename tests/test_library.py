import shutil
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import ZIPS, make_zip
from manuscript_discovery.ingest import ingest_paths
from manuscript_discovery.library import (
    Library,
    LibraryUnavailable,
    UnknownBook,
    UnknownTranslation,
)


def test_all_translations_ingested_with_metadata_from_their_files(lib):
    kjv = lib.get("eng-kjv2006")
    assert (kjv.name, kjv.abbreviation, kjv.lang, kjv.meta.script) == (
        "King James Version",
        "KJV",
        "eng",
        "Latin",
    )
    nometa = lib.get("nometa")  # no metadata files: degrade, don't fail
    assert (nometa.name, nometa.lang, nometa.abbreviation) == (
        "nometa",
        "ind",
        "nometa",
    )


def test_search_by_name_abbreviation_language_and_word(lib):
    ids = lambda **kw: [t.id for t in lib.search(**kw)]
    assert ids(q="king james") == ["eng-kjv2006"]
    assert ids(q="textus") == ["grctr"] and ids(q="TR grc") == [
        "grctr"
    ]  # words AND together
    assert set(ids(q="english")) == {"eng-kjv2006", "tiny"}
    assert ids(lang="grc") == ["grctr"]
    assert ids(q="100%_") == []  # LIKE wildcards are escaped
    assert len(lib.search(limit=2)) == 2 and len(lib.search(limit=2, offset=4)) == 1


def test_outline_uses_the_translations_own_book_names(lib):
    assert [(b.code, b.name) for b in lib.outline("grctr")] == [
        ("PSA", "Psalms"),
        ("EPH", "Ἐφεσίους"),
    ]  # canonical order
    assert list(
        next(b for b in lib.outline("eng-kjv2006") if b.code == "EPH").verses
    ) == [4, 3]
    assert list(next(b for b in lib.outline("tiny") if b.code == "EPH").verses) == [4]


def test_pieces_overlap_and_order(lib):
    got = [
        (p.chapter, p.start) for p in lib.pieces("eng-kjv2006", "EPH", (1, 3), (2, 3))
    ]
    assert got == [(1, 3), (1, 4), (2, 1), (2, 2)]  # bridge 2:2-3 included via verse 3
    assert [p.text for p in lib.pieces("eng-kjv2006", "EPH", (1, 1), (1, 1))] == [
        "Paul, an apostle of Jesus Christ"
    ]


def test_unknowns(lib):
    with pytest.raises(UnknownTranslation):
        lib.get("nope")
    with pytest.raises(UnknownTranslation):
        lib.pieces("nope", "EPH", (1, 1), (1, 1))
    with pytest.raises(UnknownBook):
        lib.pieces("tiny", "GEN", (1, 1), (1, 1))


def test_concurrent_reads(lib):
    with ThreadPoolExecutor(8) as pool:
        results = list(
            pool.map(
                lambda _: len(lib.pieces("eng-kjv2006", "EPH", (1, 1), (2, 3))),
                range(64),
            )
        )
    assert set(results) == {6}


def test_reingest_is_incremental(zips, tmp_path):
    db = tmp_path / "l.sqlite"
    assert ingest_paths([zips], db)[:2] == (5, 0)
    assert ingest_paths([zips], db)[:2] == (0, 5)  # same hashes: nothing parsed
    changed = tmp_path / "src"
    changed.mkdir()
    shutil.copy(zips / "tiny_usfx.zip", changed)
    make_zip(
        changed,
        "tiny",
        ZIPS["tiny"][0].replace("Paul, an apostle", "Paulus, an apostle"),
        *ZIPS["tiny"][1:],
    )
    assert ingest_paths([changed], db)[:2] == (1, 0)
    lib = Library(db)
    assert lib.pieces("tiny", "EPH", (1, 1), (1, 1))[0].text.startswith("Paulus")
    assert (
        len(lib.outline("tiny")) == 2 and len(lib.search()) == 5
    )  # replaced, not duplicated
    lib.close()
    conn = sqlite3.connect(db)
    assert (
        conn.execute(
            "SELECT count(*) FROM chapter WHERE translation_id='tiny'"
        ).fetchone()[0]
        == 2
    )


def test_parallel_workers_and_a_bad_file_does_not_stop_the_rest(zips, tmp_path):
    src = tmp_path / "src"
    shutil.copytree(zips, src)
    (src / "broken_usfx.zip").write_bytes(b"not a zip")
    added, unchanged, failed = ingest_paths([src], tmp_path / "l.sqlite", jobs=2)
    assert (added, unchanged, failed) == (5, 0, ["broken"])


def test_missing_library_is_a_clear_error(tmp_path):
    with pytest.raises(LibraryUnavailable, match="ingest"):
        Library(tmp_path / "absent.sqlite").search()

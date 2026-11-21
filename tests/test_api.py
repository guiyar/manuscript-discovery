import shutil

import pytest
from fastapi.testclient import TestClient

from manuscript_discovery.app import create_app
from manuscript_discovery.settings import Settings

HAS_TYPST = shutil.which(Settings().typst_bin) is not None


@pytest.fixture(scope="module")
def client(db_path):
    with TestClient(create_app(Settings(db_path=db_path))) as c:
        yield c


def render(client, **params):
    return client.get("/api/render", params={"book": "EPH", "c1": 1, **params})


def test_index_is_the_app(client):
    page = client.get("/").text
    assert "<title>Manuscript Discovery</title>" in page


def test_search_get_and_outline(client):
    found = client.get("/api/translations", params={"q": "king"}).json()
    assert found == [
        {
            "id": "eng-kjv2006",
            "name": "King James Version",
            "abbreviation": "KJV",
            "lang": "eng",
            "language": "English",
        }
    ]
    assert client.get("/api/translations/grctr").json()["abbreviation"] == "TR"
    assert client.get("/api/translations/nope").status_code == 404
    books = {b["code"]: b for b in client.get("/api/translations/grctr/outline").json()}
    assert books["EPH"] == {"code": "EPH", "name": "Ἐφεσίους", "verses": [4, 3]}


def test_plain_text(client):
    r = render(client, translation="eng-kjv2006", format="txt")
    assert r.status_code == 200 and r.text.startswith("Ephesians 1\n")
    assert "Paul, an apostle of Jesus Christ" in r.text and "Public Domain" in r.text
    assert (
        "Public Domain"
        not in render(
            client, translation="eng-kjv2006", format="txt", colophon="false"
        ).text
    )


def test_options_reach_the_document(client):
    one = render(
        client,
        translation="eng-kjv2006",
        book="PSA",
        c1=23,
        format="txt",
        poetry="false",
        colophon="false",
    )
    assert "    " not in one.text and "I shall not want." in one.text


@pytest.mark.parametrize(
    "params,status,message",
    [
        ({"translation": "nope"}, 404, "Unknown translation"),
        ({"translation": "tiny", "c1": 2}, 422, "Tiny Version has 1 chapters"),
        ({"translation": "eng-kjv2006", "v2": 9}, 422, "has 4 verses, not 9"),
        ({"translation": "eng-kjv2006", "book": "eph"}, 422, None),
        ({"translation": ["a", "b", "c"]}, 422, None),
        ({"translation": "eng-kjv2006", "paper": "../etc"}, 422, None),
        ({"translation": "bad/id"}, 422, None),
    ],
)
def test_bad_requests_say_what_is_wrong(client, params, status, message):
    r = render(client, **params)
    assert r.status_code == status
    if message:
        assert message in r.json()["detail"]


def test_missing_library_gives_503(tmp_path):
    with TestClient(create_app(Settings(db_path=tmp_path / "none.sqlite"))) as c:
        r = c.get("/api/translations")
        assert r.status_code == 503 and "ingest" in r.json()["detail"]


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
@pytest.mark.parametrize(
    "translations",
    [["eng-kjv2006"], ["grctr", "eng-kjv2006"], ["cmn2006", "eng-kjv2006"], ["nometa"]],
)
@pytest.mark.parametrize(
    "options", [{}, {"notes": "false", "line_numbers": "false", "colophon": "false"}]
)
def test_pdf(client, translations, options):
    r = render(client, translation=translations, c1=1, v1=2, c2=2, **options)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF") and len(r.content) > 4000


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
def test_markup_in_title_is_displayed_not_executed(client):
    r = render(client, translation="grctr", title='#read("/etc/passwd") *x* $y$ \\')
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

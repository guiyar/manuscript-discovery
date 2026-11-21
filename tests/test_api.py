import shutil

import pytest
from fastapi.testclient import TestClient

from bible_typeset.app import create_app
from bible_typeset.settings import Settings


@pytest.fixture(scope="module")
def client(data_dir):
    with TestClient(create_app(Settings(data_dir=data_dir))) as c:
        yield c


def test_index_and_texts(client):
    assert "Scripture typesetter" in client.get("/").text
    ids = {t["id"] for t in client.get("/api/texts").json()}
    assert ids == {"eng-kjv2006", "grctr", "cmn2006"}


def test_outline(client):
    books = {b["code"]: b for b in client.get("/api/texts/grctr/outline").json()}
    assert books["EPH"]["verses"] == [4, 3] and books["EPH"]["name"] == "Ephesians"


def test_plain_text(client):
    r = client.get(
        "/api/render",
        params={"text": "eng-kjv2006", "book": "EPH", "c1": 1, "format": "txt"},
    )
    assert r.status_code == 200 and r.text.startswith("Ephesians 1\n")
    assert "Paul, an apostle of Jesus Christ" in r.text
    assert r.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params,status",
    [
        ({"text": "nope", "book": "EPH", "c1": 1}, 404),
        ({"text": "grctr", "book": "EPH", "c1": 5}, 422),
        ({"text": "grctr", "book": "eph", "c1": 1}, 422),  # malformed book code
        (
            {"text": ["a", "b", "c"], "book": "EPH", "c1": 1},
            422,
        ),  # too many parallel texts
        ({"text": "grctr", "book": "EPH", "c1": 1, "paper": "../etc"}, 422),
    ],
)
def test_rejects_bad_input(client, params, status):
    assert client.get("/api/render", params=params).status_code == status


@pytest.mark.skipif(
    not shutil.which(Settings().typst_bin), reason="typst not installed"
)
@pytest.mark.parametrize(
    "texts", [["eng-kjv2006"], ["grctr", "eng-kjv2006"], ["cmn2006", "eng-kjv2006"]]
)
def test_pdf(client, texts):
    r = client.get(
        "/api/render", params={"text": texts, "book": "EPH", "c1": 1, "v1": 2, "c2": 2}
    )
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF") and len(r.content) > 5000
    assert r.headers["content-disposition"].startswith("inline")


@pytest.mark.skipif(
    not shutil.which(Settings().typst_bin), reason="typst not installed"
)
def test_markup_in_title_is_displayed_not_executed(client):
    r = client.get(
        "/api/render",
        params={
            "text": "grctr",
            "book": "EPH",
            "c1": 1,
            "title": '#read("/etc/passwd") *x* $y$ \\',
        },
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

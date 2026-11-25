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
    kept = render(
        client,
        translation="eng-kjv2006",
        c1=1,
        v2=4,
        format="txt",
        colophon="false",
        paragraphs="true",
    )
    assert (
        kept.text.count("\n\n") == 2
        and render(
            client,
            translation="eng-kjv2006",
            c1=1,
            v2=4,
            format="txt",
            colophon="false",
        ).text.count("\n\n")
        == 1
    )  # default: one paragraph


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
        ({"translation": "eng-kjv2006", "line_spacing": "3"}, 422, None),
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


# --- live preview (PNG) ----------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n"


def preview(client, **params):
    return client.get(
        "/api/preview",
        params={"translation": "eng-kjv2006", "book": "EPH", "c1": 1, **params},
    )


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
def test_preview_returns_cacheable_low_resolution_pngs(client):
    info = preview(client).json()
    assert info["pages"] >= 1 and info["complete"] is True and len(info["key"]) == 32
    r = client.get(f"/api/preview/{info['key']}/1.png")
    assert r.status_code == 200 and r.content.startswith(PNG)
    assert "immutable" in r.headers["cache-control"]
    width = int.from_bytes(r.content[16:20], "big")
    assert width < 1000, (
        "preview must be screen resolution, not print resolution (A4 at 300 ppi is 2480 px)"
    )


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
def test_identical_settings_are_served_from_cache_changed_ones_are_not(
    db_path, monkeypatch
):
    import manuscript_discovery.app as app_module

    calls = []
    real = app_module.render_png

    async def counting(*a, **kw):
        calls.append(1)
        return await real(*a, **kw)

    monkeypatch.setattr(app_module, "render_png", counting)
    with TestClient(create_app(Settings(db_path=db_path))) as c:
        k1 = preview(c).json()["key"]
        assert preview(c).json()["key"] == k1 and len(calls) == 1  # repeat: no render
        assert preview(c, title="Other").json()["key"] != k1 and len(calls) == 2
        assert (
            preview(c).json()["key"] == k1 and len(calls) == 2
        )  # back to the first: still cached


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
def test_long_selections_are_cut_and_say_so(db_path, monkeypatch):
    from manuscript_discovery.document import Document

    monkeypatch.setattr(Document, "preview_chars", lambda self, pages: 10)
    with TestClient(create_app(Settings(db_path=db_path, preview_pages=1))) as c:
        info = preview(c, c2=2).json()
        assert info["complete"] is False and info["pages"] == 1


def test_preview_errors_are_the_same_clear_ones(client):
    assert "has 4 verses, not 9" in preview(client, v2=9).json()["detail"]
    assert preview(client, translation="nope").status_code == 404
    assert (
        client.get("/api/preview/" + "0" * 32 + "/1.png").status_code == 404
    )  # expired / unknown
    assert client.get("/api/preview/not-a-key/1.png").status_code == 422


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
def test_pages_past_the_end_are_404(client):
    key = preview(client).json()["key"]
    assert client.get(f"/api/preview/{key}/99.png").status_code == 404


def test_health_reports_typst_and_cjk_capability(client):
    import time

    for _ in range(50):
        body = client.get("/api/health").json()
        if body != {"status": "checking"}:
            break
        time.sleep(0.1)
    assert set(body) == {"version", "typst", "cjk_png", "ok"} and (
        body["typst"] is None or body["typst"].startswith("typst")
    )


@pytest.mark.skipif(not HAS_TYPST, reason="typst not installed")
@pytest.mark.parametrize("spacing", ["1.5", "2"])
def test_both_line_spacings_typeset(client, spacing):
    r = render(
        client,
        translation=["eng-kjv2006", "cmn2006"],
        c1=1,
        v1=1,
        c2=2,
        line_spacing=spacing,
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert preview(client, line_spacing=spacing).status_code == 200


@pytest.mark.parametrize("offset", [-1, 100_001, 2**63, 10**100])
def test_invalid_search_offsets_are_rejected(client, offset):
    assert client.get("/api/translations", params={"offset": offset}).status_code == 422


def test_search_offset_boundary(client):
    assert client.get("/api/translations", params={"offset": 100_000}).json() == []
    first = client.get("/api/translations", params={"limit": 1, "offset": 0}).json()
    second = client.get("/api/translations", params={"limit": 1, "offset": 1}).json()
    assert first and second and first != second

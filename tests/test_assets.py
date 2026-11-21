import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from manuscript_discovery import assets
from manuscript_discovery.app import create_app
from manuscript_discovery.settings import Settings

SOURCE = Path(assets.__file__).parent / "static"
HAS_MINIFY = shutil.which("minify") is not None


@pytest.fixture()
def static_copy(tmp_path):
    """A scratch copy of the real UI source, so building never touches the repository."""
    shutil.copytree(SOURCE, tmp_path / "static", ignore=shutil.ignore_patterns("dist"))
    return tmp_path / "static"


def test_serving_root_prefers_the_minified_build_and_falls_back_to_source(tmp_path):
    assert assets.serving_root(tmp_path) == tmp_path
    (tmp_path / "dist").mkdir()
    assert assets.serving_root(tmp_path) == tmp_path  # an empty dist is not a build
    (tmp_path / "dist" / "index.html").write_text("x")
    assert assets.serving_root(tmp_path) == tmp_path / "dist"


def test_a_missing_minifier_is_a_clear_error(static_copy):
    with pytest.raises(FileNotFoundError, match="minify"):
        assets.build(static_copy, minify_bin="definitely-not-installed")


@pytest.mark.skipif(not HAS_MINIFY, reason="minify not installed")
def test_build_minifies_html_css_and_js_inline_and_is_repeatable(static_copy):
    (static_copy / "extra.css").write_text(
        "body {  color : red ;  }\n\n/* comment */\n"
    )
    (static_copy / "extra.js").write_text(
        "// comment\nconst   answer  =  42 ;\nconsole.log( answer );\n"
    )
    written = {p.name: p for p in assets.build(static_copy)}
    assert set(written) == {"index.html", "extra.css", "extra.js"}
    html = (static_copy / "index.html").read_text(), written["index.html"].read_text()
    assert len(html[1]) < 0.85 * len(html[0])  # inline CSS and JS shrink too
    assert (
        "<title>Manuscript Discovery</title>" in html[1]
        and "Manuscript Discovery" in html[1]
    )
    assert written["extra.css"].read_text() == "body{color:red}"
    assert "comment" not in written["extra.js"].read_text()
    assert [p.name for p in assets.build(static_copy)] == sorted(
        written
    )  # rebuilding replaces, never accumulates


def client_for(db_path, **kw):
    return TestClient(create_app(Settings(db_path=db_path, **kw)))


def test_the_ui_is_served_with_revalidation_and_conditional_requests(
    db_path, static_copy
):
    with client_for(db_path, static_dir=static_copy) as c:
        first = c.get("/")
        assert (
            first.status_code == 200
            and "<title>Manuscript Discovery</title>" in first.text
        )
        assert first.headers["cache-control"] == "no-cache" and first.headers["etag"]
        again = c.get("/", headers={"If-None-Match": first.headers["etag"]})
        assert (
            again.status_code == 304 and again.content == b""
        )  # unchanged: no body sent
        assert c.get("/index.html").status_code == 200
        assert c.get("/nothing-here").status_code == 404


def test_the_ui_mount_never_shadows_the_api(db_path, static_copy):
    with client_for(db_path, static_dir=static_copy) as c:
        assert c.get("/api/translations").json()
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/translations/nope").status_code == 404


@pytest.mark.skipif(not HAS_MINIFY, reason="minify not installed")
def test_what_is_served_is_the_minified_build_when_there_is_one(db_path, static_copy):
    source_size = len((static_copy / "index.html").read_bytes())
    assets.build(static_copy)
    with client_for(db_path, static_dir=assets.serving_root(static_copy)) as c:
        served = c.get("/").content
    assert len(served) < 0.85 * source_size and b"Manuscript Discovery" in served

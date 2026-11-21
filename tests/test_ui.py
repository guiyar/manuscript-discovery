"""Runs the browser-less UI tests (tests/ui, Node + jsdom) against real servers.

They run twice: against the readable source, and against the minified build that is actually
shipped, so a minifier that breaks the page is caught. Setup once: `cd tests/ui && npm ci`.
Deselect with `-m "not ui"`.
"""

import contextlib
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from conftest import ZIPS, make_zip
from manuscript_discovery import assets
from manuscript_discovery.app import create_app
from manuscript_discovery.ingest import ingest_paths
from manuscript_discovery.settings import Settings

UI = Path(__file__).parent / "ui"
SOURCE = Path(assets.__file__).parent / "static"
pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _requirements():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if not (UI / "node_modules" / "jsdom").is_dir():
        pytest.skip("run `npm ci` in tests/ui first")
    if not shutil.which(Settings().typst_bin):
        pytest.skip("typst not installed (the previews need it)")


@pytest.fixture(scope="module", params=["source", "minified"])
def static_dir(request, tmp_path_factory):
    copy = tmp_path_factory.mktemp("ui-static") / "static"
    shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns("dist"))
    if request.param == "source":
        return copy
    if not shutil.which("minify"):
        pytest.skip("minify not installed")
    assets.build(copy)
    return copy / "dist"


@pytest.fixture(scope="module")
def library_without_the_default_translation(tmp_path_factory):
    src = tmp_path_factory.mktemp("zips-no-kjv")
    for tid, parts in ZIPS.items():
        if tid != "eng-kjv2006":
            make_zip(src, tid, *parts)
    db = tmp_path_factory.mktemp("db-no-kjv") / "library.sqlite"
    ingest_paths([src], db)
    return db


@contextlib.contextmanager
def serve(**settings):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Settings(**settings)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)


def test_the_ui_in_a_browser_like_environment(
    static_dir, db_path, library_without_the_default_translation
):
    with (
        serve(db_path=db_path, static_dir=static_dir) as base,
        serve(
            db_path=library_without_the_default_translation, static_dir=static_dir
        ) as base_without,
    ):
        run = subprocess.run(
            ["node", "--test", "--test-concurrency=1"],
            cwd=UI,
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "UI_BASE_URL": base, "UI_BASE_URL_NO_KJV": base_without},
        )
    assert run.returncode == 0, (
        f"UI tests failed against {static_dir}:\n{run.stdout[-7000:]}\n{run.stderr[-2000:]}"
    )

"""What the app itself must guarantee when it is the thing facing a (proxied) public internet."""

import asyncio
import base64
import hashlib
import re
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from manuscript_discovery import __main__ as cli
from manuscript_discovery import assets
from manuscript_discovery.app import create_app
from manuscript_discovery.security import content_security_policy
from manuscript_discovery.settings import Settings
from manuscript_discovery.typeset import Busy, Gate

SOURCE = Path(assets.__file__).parent / "static"
HAS_MINIFY = shutil.which("minify") is not None


def client(db_path, **kw):
    return TestClient(create_app(Settings(db_path=db_path, **kw)))


# --- security headers and the CSP ---------------------------------------------------------------


def served_variants(tmp_path):
    """The UI exactly as it would be served: readable source, and the minified build."""
    copy = tmp_path / "static"
    shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns("dist"))
    variants = {"source": copy}
    if HAS_MINIFY:
        assets.build(copy)
        variants["minified"] = copy / "dist"
    return variants


def test_every_response_carries_the_security_headers(db_path):
    with client(db_path) as c:
        for path in (
            "/",
            "/api/translations",
            "/api/health",
            "/healthz",
            "/nothing-here",
        ):
            h = c.get(path).headers
            assert h["x-content-type-options"] == "nosniff", path
            assert (
                h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
            ), path
            assert "frame-ancestors 'none'" in h["content-security-policy"], path
            assert h["cross-origin-resource-policy"] == "same-origin", path


def _digest(text):
    # Recompute the hashes independently of the app's own parser.
    return (
        "'sha256-"
        + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        + "'"
    )


def test_the_csp_allows_exactly_the_inline_code_the_page_contains(db_path, tmp_path):
    for name, root in served_variants(tmp_path).items():
        html = (root / "index.html").read_text("utf-8")
        with client(db_path, static_dir=root) as c:
            csp = c.get("/").headers["content-security-policy"]

        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        styles = re.findall(r"<style>(.*?)</style>", html, re.S)
        assert scripts and styles, name
        assert f"script-src {' '.join(map(_digest, scripts))};" in csp + ";", name
        assert f"style-src {' '.join(map(_digest, styles))};" in csp + ";", name
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp, name


def test_the_page_uses_nothing_the_csp_would_block(tmp_path):
    """A browser would refuse any of these, silently breaking the UI. Checked on both builds."""
    for name, root in served_variants(tmp_path).items():
        html = (root / "index.html").read_text("utf-8")
        markup = re.sub(r"<(script|style)>.*?</\1>", "", html, flags=re.S)
        assert not re.search(r"\son[a-z]+\s*=", markup), f"{name}: inline event handler"
        assert not re.search(r"\sstyle\s*=", markup), f"{name}: inline style attribute"
        assert "javascript:" not in markup, name
        assert not re.search(r"(src|href|action)\s*=\s*[\"']?(https?:)?//", markup), (
            f"{name}: external resource"
        )
        script = " ".join(re.findall(r"<script>(.*?)</script>", html, re.S))
        assert not re.search(
            r"\beval\s*\(|new\s+Function\s*\(|\.innerHTML\s*=|document\.write", script
        ), name


def test_a_page_with_no_inline_code_gets_a_closed_policy():
    csp = content_security_policy("<html><body>hi</body></html>")
    assert (
        "script-src 'none'" in csp
        and "style-src 'none'" in csp
        and "default-src 'none'" in csp
    )


def test_a_changed_script_gets_a_different_hash():
    a = content_security_policy("<script>run(1)</script>")
    assert a != content_security_policy("<script>run(2)</script>")
    assert (
        content_security_policy("<script src='x.js'></script>").count("sha256") == 0
    )  # external: not allowed by hash


def test_api_docs_and_schema_are_not_exposed(db_path):
    with client(db_path) as c:
        for path in ("/api/docs", "/docs", "/redoc", "/openapi.json"):
            assert c.get(path).status_code == 404, path


def test_favicon_requests_are_cheap_and_quiet(db_path):
    with client(db_path) as c:
        r = c.get("/favicon.ico")
        assert r.status_code == 204 and "max-age" in r.headers["cache-control"]


# --- liveness, readiness, version ---------------------------------------------------------------


def test_healthz_is_always_up_and_readyz_says_when_it_can_serve(db_path, monkeypatch):
    monkeypatch.setattr(
        shutil, "which", lambda name: "/test/typst" if name == "typst" else None
    )
    with client(db_path) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
        ready = c.get("/readyz")
        assert ready.status_code == 200
        body = ready.json()
        assert (
            body["ready"] is True
            and body["translations"] >= 5
            and body["problems"] == []
        )


def test_not_ready_without_a_library_an_empty_one_or_typst(
    db_path, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        shutil, "which", lambda name: "/test/typst" if name == "typst" else None
    )
    with client(tmp_path / "none.sqlite") as c:
        r = c.get("/readyz")
        assert r.status_code == 503 and "ingest" in r.json()["problems"][0]
        assert c.get("/healthz").status_code == 200  # alive, just not ready
    empty = tmp_path / "empty.sqlite"
    from manuscript_discovery.library import LibraryWriter

    LibraryWriter(empty).close()
    with client(empty) as c:
        assert c.get("/readyz").json()["problems"] == [
            "the library has no translations"
        ]
    with client(db_path, typst_bin="/nonexistent/typst") as c:
        r = c.get("/readyz")
        assert r.status_code == 503 and "Typst not found" in r.json()["problems"][0]


def test_health_reports_the_version(db_path):
    from manuscript_discovery import __version__

    with client(db_path) as c:
        assert c.get("/api/health").json()["version"] == __version__


# --- load shedding ------------------------------------------------------------------------------


def test_gate_queues_up_to_its_limit_then_refuses():
    async def scenario():
        gate = Gate(slots=1, max_waiting=1)
        holder_in, release = asyncio.Event(), asyncio.Event()

        async def hold():
            async with gate:
                holder_in.set()
                await release.wait()

        running = asyncio.create_task(hold())
        await holder_in.wait()
        waiter = asyncio.create_task(hold())  # allowed to queue
        await asyncio.sleep(0.01)
        assert gate.waiting == 1
        with pytest.raises(Busy):  # one too many
            async with gate:
                pass
        release.set()
        await asyncio.gather(running, waiter)
        async with gate:  # and it recovers completely
            pass
        assert gate.waiting == 0

    asyncio.run(scenario())


def test_a_cancelled_waiter_gives_back_its_place():
    async def scenario():
        gate = Gate(slots=1, max_waiting=1)
        release = asyncio.Event()

        async def hold():
            async with gate:
                await release.wait()

        running = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        waiter = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        assert gate.waiting == 0  # the queue place is free again
        release.set()
        await running

    asyncio.run(scenario())


def test_a_burst_gets_503_with_retry_after_while_the_server_stays_responsive(
    db_path, monkeypatch
):
    import manuscript_discovery.app as app_module

    builds = []
    real_build = app_module.build_document

    def counting_build(*args):
        builds.append(1)
        return real_build(*args)

    monkeypatch.setattr(app_module, "build_document", counting_build)

    async def slow_png(data, settings, gate, abort=None):
        async with gate:
            await asyncio.sleep(0.5)
        return [b"\x89PNG"]

    monkeypatch.setattr(app_module, "render_png", slow_png)
    app = create_app(Settings(db_path=db_path, max_concurrent=1, max_waiting=2))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            burst = [
                c.get(
                    "/api/preview",
                    params={
                        "translation": "eng-kjv2006",
                        "book": "EPH",
                        "c1": 1,
                        "title": f"burst {i}",
                    },
                )
                for i in range(8)
            ]
            probe = asyncio.create_task(asyncio.sleep(0.15))
            results = asyncio.gather(*burst)
            await probe
            health = await c.get("/healthz")  # answered while renders are queued
            return health.status_code, await results

    health_status, responses = asyncio.run(scenario())
    codes = sorted(r.status_code for r in responses)
    assert health_status == 200
    assert codes.count(200) == 3 and codes.count(503) == 5, (
        codes
    )  # 1 running + 2 queued, rest refused
    assert len(builds) == 3  # rejected requests never load or decompress chapters
    refused = next(r for r in responses if r.status_code == 503)
    assert refused.headers["retry-after"] == "5" and "busy" in refused.json()["detail"]


@pytest.mark.parametrize(
    "path,output",
    [
        ("/api/preview", "pdf"),
        ("/api/render", "pdf"),
        ("/api/render", "txt"),
    ],
)
def test_document_admission_precedes_building_and_is_shared(
    db_path, monkeypatch, path, output
):
    import manuscript_discovery.app as app_module

    real_threadpool = app_module.run_in_threadpool

    async def scenario():
        building, release_build = asyncio.Event(), asyncio.Event()
        rendering, release_render = asyncio.Event(), asyncio.Event()
        builds = []

        async def slow_build(func, *args):
            if func is app_module.build_document:
                builds.append(1)
                building.set()
                await release_build.wait()
            return await real_threadpool(func, *args)

        async def slow_render(data, settings, gate, abort=None):
            async with gate:
                rendering.set()
                await release_render.wait()
            return [b"\x89PNG"] if path == "/api/preview" else b"%PDF"

        monkeypatch.setattr(app_module, "run_in_threadpool", slow_build)
        monkeypatch.setattr(app_module, "render_png", slow_render)
        monkeypatch.setattr(app_module, "render_pdf", slow_render)
        app = create_app(Settings(db_path=db_path, max_concurrent=1, max_waiting=0))
        params = {"translation": "eng-kjv2006", "book": "EPH", "c1": 1}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            running = asyncio.create_task(
                c.get(path, params={**params, "format": output})
            )

            async def assert_busy():
                for route, fmt in (
                    ("/api/preview", "pdf"),
                    ("/api/render", "pdf"),
                    ("/api/render", "txt"),
                ):
                    r = await c.get(route, params={**params, "format": fmt})
                    assert r.status_code == 503
                    assert r.headers["retry-after"] == "5"
                assert len(builds) == 1
                assert (await c.get("/healthz")).status_code == 200

            try:
                await asyncio.wait_for(building.wait(), timeout=5)
                await assert_busy()
                release_build.set()
                if output == "pdf":
                    await asyncio.wait_for(rendering.wait(), timeout=5)
                    await (
                        assert_busy()
                    )  # the admission slot survives document construction
            finally:
                release_build.set()
                release_render.set()
                await asyncio.wait_for(running, timeout=5)
            assert running.result().status_code == 200
            # The slot is returned after success and after a selection error.
            invalid = await c.get("/api/render", params={**params, "v2": 200})
            assert invalid.status_code == 422
            recovered = await c.get("/api/render", params={**params, "format": "txt"})
            assert recovered.status_code == 200

    asyncio.run(scenario())


# --- configuration ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,message",
    [
        ({"MANUSCRIPT_PORT": "70000"}, "MANUSCRIPT_PORT"),
        ({"MANUSCRIPT_MAX_CONCURRENT": "0"}, "MANUSCRIPT_MAX_CONCURRENT"),
        ({"MANUSCRIPT_TIMEOUT_S": "-1"}, "MANUSCRIPT_TIMEOUT_S"),
        ({"MANUSCRIPT_PREVIEW_PPI": "10"}, "MANUSCRIPT_PREVIEW_PPI"),
        ({"MANUSCRIPT_LOG_LEVEL": "chatty"}, "MANUSCRIPT_LOG_LEVEL"),
    ],
)
def test_bad_configuration_stops_startup_naming_the_variable(
    monkeypatch, capsys, env, message
):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert cli.main(["serve"]) == 2
    assert message in capsys.readouterr().err


def test_serve_trusts_forwarded_headers_only_from_the_configured_proxies(
    monkeypatch, db_path
):
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: seen.update(kw))
    monkeypatch.setenv("MANUSCRIPT_DB_PATH", str(db_path))
    monkeypatch.setenv("MANUSCRIPT_TRUSTED_PROXIES", "10.0.0.5")
    assert cli.main(["serve"]) == 0
    assert seen["proxy_headers"] is True and seen["forwarded_allow_ips"] == "10.0.0.5"
    assert seen["server_header"] is False and seen["timeout_graceful_shutdown"] > 0


def test_identical_previews_share_render_and_one_cancel_does_not_kill_it(
    db_path, monkeypatch
):
    import manuscript_discovery.app as app_module

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0
        builds = 0
        both_built = asyncio.Event()
        real_threadpool = app_module.run_in_threadpool

        async def count_build(func, *args):
            nonlocal builds
            result = await real_threadpool(func, *args)
            if func is app_module.build_document:
                builds += 1
                if builds == 2:
                    both_built.set()
            return result

        async def slow_png(data, settings, gate, abort=None):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return [b"\x89PNG"]

        monkeypatch.setattr(app_module, "run_in_threadpool", count_build)
        monkeypatch.setattr(app_module, "render_png", slow_png)
        app = create_app(Settings(db_path=db_path, max_concurrent=2, max_waiting=0))
        params = {"translation": "eng-kjv2006", "book": "EPH", "c1": 1}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            a = asyncio.create_task(c.get("/api/preview", params=params))
            await asyncio.wait_for(entered.wait(), 5)
            b = asyncio.create_task(c.get("/api/preview", params=params))
            await asyncio.wait_for(both_built.wait(), 5)
            a.cancel()
            await asyncio.gather(a, return_exceptions=True)
            release.set()
            result = await asyncio.wait_for(b, 5)
            assert result.status_code == 200
            assert calls == 1
            assert (await c.get("/api/preview", params=params)).json() == result.json()
            assert calls == 1

    asyncio.run(scenario())


def test_abandoned_preview_is_cancelled_and_can_be_retried(db_path, monkeypatch):
    import manuscript_discovery.app as app_module

    async def scenario():
        entered = asyncio.Event()
        stopped = asyncio.Event()
        calls = 0

        async def slow_png(data, settings, gate, abort=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            return [b"\x89PNG"]

        monkeypatch.setattr(app_module, "render_png", slow_png)
        app = create_app(Settings(db_path=db_path, max_concurrent=1, max_waiting=0))
        params = {"translation": "eng-kjv2006", "book": "EPH", "c1": 1}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            a = asyncio.create_task(c.get("/api/preview", params=params))
            await asyncio.wait_for(entered.wait(), 5)
            a.cancel()
            await asyncio.gather(a, return_exceptions=True)
            assert stopped.is_set()
            assert (await c.get("/api/preview", params=params)).status_code == 200
            assert calls == 2

    asyncio.run(scenario())


def test_library_failure_does_not_expose_paths(tmp_path, caplog):
    db = tmp_path / "private-library.sqlite"
    with client(db, typst_bin="/private/bin/typst") as c:
        response = c.get("/api/translations")
        assert response.status_code == 503
        assert response.json() == {"detail": "Library unavailable"}
        readiness = c.get("/readyz")
        assert readiness.status_code == 503
        assert str(db) not in readiness.text
        assert "/private/bin/typst" not in readiness.text
    assert str(db) in caplog.text

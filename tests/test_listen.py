"""Serving on a Unix socket: created with the permissions we choose, never world-writable."""

import logging
import os
import socket
import stat
import threading
import time

import httpx
import pytest
import uvicorn

from manuscript_discovery import __main__ as cli
from manuscript_discovery.app import create_app
from manuscript_discovery.listen import SOCKET_MODE, bind_unix_socket
from manuscript_discovery.settings import Settings


def mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.parametrize("umask", [0o000, 0o022, 0o077])
def test_the_socket_is_created_with_exactly_0660_whatever_the_umask(tmp_path, umask):
    previous = os.umask(umask)
    try:
        sock = bind_unix_socket(tmp_path / "app.sock")
        assert (
            os.umask(previous) == umask
        )  # restored, so the rest of the process is unaffected
    finally:
        os.umask(previous)
    assert mode(tmp_path / "app.sock") == SOCKET_MODE == 0o660
    sock.close()


def test_a_stale_socket_file_from_a_crash_is_replaced(tmp_path):
    path = tmp_path / "app.sock"
    bind_unix_socket(
        path
    ).close()  # closed without removing the file: what a crash leaves
    assert path.exists()
    bind_unix_socket(path).close()


def test_a_live_listener_is_never_taken_over(tmp_path):
    path = tmp_path / "app.sock"
    live = bind_unix_socket(path)
    live.listen()
    with pytest.raises(OSError, match="already listening"):
        bind_unix_socket(path)
    assert path.exists()
    live.close()


def test_anything_that_is_not_a_socket_is_refused_not_deleted(tmp_path):
    path = tmp_path / "precious.txt"
    path.write_text("do not delete")
    with pytest.raises(FileExistsError, match="not a socket"):
        bind_unix_socket(path)
    assert path.read_text() == "do not delete"


def test_a_missing_directory_says_what_to_do(tmp_path):
    with pytest.raises(FileNotFoundError, match="RuntimeDirectory"):
        bind_unix_socket(tmp_path / "missing" / "app.sock")


def test_the_socket_path_must_be_absolute():
    with pytest.raises(ValueError, match="absolute"):
        Settings(unix_socket="app.sock")


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, "127.0.0.1"),
        (
            {"unix_socket": "/run/app.sock"},
            "*",
        ),  # on a socket, file permissions decide who may connect
        ({"unix_socket": "/run/app.sock", "trusted_proxies": "10.1.1.1"}, "10.1.1.1"),
        ({"trusted_proxies": "10.1.1.1"}, "10.1.1.1"),
    ],
)
def test_forwarded_headers_are_trusted_by_default_only_where_it_is_safe(
    kwargs, expected
):
    assert Settings(**kwargs).forwarded_allow_ips == expected


class _Served:
    """A real uvicorn server on a Unix socket, with its access log captured."""

    def __init__(self, db_path, socket_path, **settings):
        self.path = socket_path
        s = Settings(db_path=db_path, unix_socket=socket_path, **settings)
        config = uvicorn.Config(
            create_app(s),
            proxy_headers=True,
            forwarded_allow_ips=s.forwarded_allow_ips,
            server_header=False,
            log_level="info",
        )
        self.server = uvicorn.Server(config)
        self.sock = bind_unix_socket(socket_path)
        self.clients = []
        outer = self

        class Capture(logging.Handler):
            def emit(self, record):
                outer.clients.append(
                    record.args[0]
                )  # the client address uvicorn logged

        self.handler = Capture()

    def __enter__(self):
        logging.getLogger("uvicorn.access").addHandler(self.handler)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True
        )
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            assert self.thread.is_alive() and time.monotonic() < deadline
            time.sleep(0.05)
        return self

    def get(self, path, **headers):
        transport = httpx.HTTPTransport(uds=str(self.path))
        with httpx.Client(transport=transport, base_url="http://app") as client:
            return client.get(path, headers=headers)

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(15)
        logging.getLogger("uvicorn.access").removeHandler(self.handler)


def test_the_app_is_served_over_the_socket(db_path, tmp_path):
    with _Served(db_path, tmp_path / "app.sock") as served:
        r = served.get("/healthz")
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert "server" not in r.headers
        assert served.get("/api/translations").json()
        assert mode(tmp_path / "app.sock") == 0o660


def test_a_forwarded_client_address_is_honoured_over_the_socket_by_default(
    db_path, tmp_path
):
    with _Served(db_path, tmp_path / "app.sock") as served:
        served.get("/healthz", **{"X-Forwarded-For": "203.0.113.9"})
    assert served.clients[-1].startswith("203.0.113.9")


def test_an_explicit_proxy_list_still_overrides_the_default(db_path, tmp_path):
    """Peers on a socket have no address, so a list of IPs matches none of them: header ignored."""
    with _Served(db_path, tmp_path / "app.sock", trusted_proxies="10.1.1.1") as served:
        served.get("/healthz", **{"X-Forwarded-For": "203.0.113.9"})
    assert not served.clients[-1].startswith("203.0.113.9")


def test_serve_binds_the_socket_and_runs_uvicorn_on_it(monkeypatch, db_path, tmp_path):
    seen = {}

    def fake_run(self, sockets=None):
        seen["sockets"] = sockets
        seen["mode"] = mode(tmp_path / "app.sock")
        seen["trusted"] = self.config.forwarded_allow_ips

    monkeypatch.setattr(cli.uvicorn.Server, "run", fake_run)
    monkeypatch.setenv("MANUSCRIPT_DB_PATH", str(db_path))
    monkeypatch.setenv("MANUSCRIPT_UNIX_SOCKET", str(tmp_path / "app.sock"))
    assert cli.main(["serve"]) == 0
    assert len(seen["sockets"]) == 1 and seen["sockets"][0].family == socket.AF_UNIX
    assert seen["mode"] == 0o660 and seen["trusted"] == "*"
    for sock in seen["sockets"]:
        sock.close()  # the fake run never serves, so nothing else would


def test_serve_reports_a_socket_that_cannot_be_bound(
    monkeypatch, db_path, tmp_path, capsys
):
    monkeypatch.setenv("MANUSCRIPT_DB_PATH", str(db_path))
    monkeypatch.setenv("MANUSCRIPT_UNIX_SOCKET", str(tmp_path / "missing" / "app.sock"))
    assert cli.main(["serve"]) == 1
    assert "cannot listen on" in capsys.readouterr().err

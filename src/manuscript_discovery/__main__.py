import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from . import assets
from .app import create_app
from .ingest import ingest_paths
from .listen import bind_unix_socket
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manuscript-discovery")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the web app (default)")
    sub.add_parser(
        "build-assets",
        help="minify the web UI into static/dist (needs `minify` on PATH)",
    )
    ing = sub.add_parser(
        "ingest", help="add or refresh translations from eBible *_usfx.zip files"
    )
    ing.add_argument(
        "paths", nargs="+", type=Path, help="zip files, or folders of them"
    )
    ing.add_argument(
        "--db", type=Path, help="library database (default: MANUSCRIPT_DB_PATH)"
    )
    ing.add_argument("-j", "--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ing.add_argument(
        "--force", action="store_true", help="re-read files even if unchanged"
    )
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except (
        ValidationError
    ) as e:  # stop at once, naming each offending variable, rather than misbehave later
        for err in e.errors():
            print(
                f"error: MANUSCRIPT_{str(err['loc'][0]).upper()}: {err['msg']}",
                file=sys.stderr,
            )
        return 2
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(message)s"
    )

    if args.cmd == "build-assets":
        written = assets.build(Path(__file__).parent / "static")
        print(
            f"minified {len(written)} file(s): "
            + ", ".join(f"{p.name} ({p.stat().st_size} B)" for p in written)
        )
        return 0
    if args.cmd == "ingest":
        added, unchanged, failed = ingest_paths(
            args.paths, args.db or settings.db_path, args.jobs, args.force
        )
        print(f"{added} added or updated, {unchanged} unchanged, {len(failed)} failed")
        return 1 if failed else 0
    app = create_app(settings)
    options = {
        "log_level": settings.log_level,
        # Behind a reverse proxy: take the client address from X-Forwarded-For, but only from the proxies
        # named here, so a client reaching the port directly cannot forge it.
        "proxy_headers": True,
        "forwarded_allow_ips": settings.forwarded_allow_ips,
        "server_header": False,  # do not advertise the server software
        "timeout_graceful_shutdown": 15,  # let requests in flight finish on SIGTERM, then stop
    }
    if settings.unix_socket:
        try:
            sock = bind_unix_socket(settings.unix_socket)
        except OSError as e:
            print(
                f"error: cannot listen on {settings.unix_socket}: {e}", file=sys.stderr
            )
            return 1
        uvicorn.Server(uvicorn.Config(app, **options)).run(sockets=[sock])
    else:
        uvicorn.run(app, host=settings.host, port=settings.port, **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

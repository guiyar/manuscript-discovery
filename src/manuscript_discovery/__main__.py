import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .app import create_app
from .ingest import ingest_paths
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="manuscript-discovery")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the web app (default)")
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
    settings = Settings()

    if args.cmd == "ingest":
        added, unchanged, failed = ingest_paths(
            args.paths, args.db or settings.db_path, args.jobs, args.force
        )
        print(f"{added} added or updated, {unchanged} unchanged, {len(failed)} failed")
        return 1 if failed else 0
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

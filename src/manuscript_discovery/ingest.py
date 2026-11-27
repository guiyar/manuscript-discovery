"""`manuscript-discovery ingest`: read eBible USFX zips into the library database.

Unchanged files (same SHA-256) are skipped before any parsing, so re-running over thousands of
zips only does work for what changed. Parsing is CPU-bound and runs in worker processes; one
writer in this process stores the results.
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import NamedTuple

from .library import LibraryWriter, Translation
from .metadata import Metadata, read_metadata
from .usfx import Parsed, load_usfx

log = logging.getLogger(__name__)
SUFFIX = "_usfx.zip"
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class Source(NamedTuple):
    parsed: Parsed
    meta: Metadata


def read_source(path: str) -> Source:  # top level so worker processes can run it
    with open(path, "rb") as f:
        if f.seek(0, 2) > _MAX_ARCHIVE_BYTES:
            raise ValueError("USFX archive exceeds compressed size limit")
        f.seek(0)
        with zipfile.ZipFile(f) as zf:
            parsed = load_usfx(zf)
            return Source(
                parsed, read_metadata(zf, fallback_language=parsed.language_code)
            )


def translation_id(path: Path) -> str:
    return path.name.removesuffix(SUFFIX) if path.name.endswith(SUFFIX) else path.stem


def discover(paths: list[Path]) -> list[Path]:
    return [
        f for p in paths for f in (sorted(p.glob(f"*{SUFFIX}")) if p.is_dir() else [p])
    ]


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def ingest_paths(
    paths: list[Path], db_path: Path, jobs: int = 1, force: bool = False
) -> tuple[int, int, list[str]]:
    """Returns (added, unchanged, failed ids). A bad file is logged and skipped."""
    writer = LibraryWriter(db_path)
    unchanged, failed = 0, []
    todo: list[tuple[Path, str, str]] = []
    added = 0
    try:
        for f in discover(paths):
            tid = translation_id(f)
            try:
                if f.stat().st_size > _MAX_ARCHIVE_BYTES:
                    raise ValueError("USFX archive exceeds compressed size limit")
                digest = _sha256(f)
            except (OSError, ValueError) as e:
                log.error("%s: %s", tid, e)
                failed.append(tid)
                continue
            if not force and writer.current_sha(tid) == digest:
                unchanged += 1
            else:
                todo.append((f, tid, digest))

        def store(item: tuple[Path, str, str], src: Source) -> None:
            nonlocal added
            _, tid, digest = item
            meta = src.meta
            t = Translation(
                tid, meta.name or tid, meta.language or tid[:3].lower(), meta, digest
            )
            n = writer.add(t, src.parsed.books, src.parsed.book_names)
            added += 1
            log.info("ingested %s (%s): %d pieces", tid, t.name, n)

        def attempt(item, get_source) -> None:
            try:
                store(item, get_source())
            except Exception as e:  # noqa: BLE001 - one bad file must not abort thousands of others
                log.error("%s: %s", item[1], e)
                failed.append(item[1])

        if jobs <= 1:
            for item in todo:
                attempt(item, lambda item=item: read_source(str(item[0])))
        else:
            with ProcessPoolExecutor(jobs) as pool:
                queue, pending = iter(todo), {}

                def refill() -> (
                    None
                ):  # bounded window keeps parsed results from piling up
                    for item in queue:
                        pending[pool.submit(read_source, str(item[0]))] = item
                        if len(pending) >= jobs * 2:
                            break

                refill()
                while pending:
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for fut in done:
                        attempt(pending.pop(fut), fut.result)
                    refill()
    finally:
        writer.close()
    return added, unchanged, failed

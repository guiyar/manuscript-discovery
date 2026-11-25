"""Run Typst on a document. Scripture text travels as JSON data, never as Typst source,
so no escaping is needed and the text cannot inject markup or file access."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from .settings import Settings

log = logging.getLogger(__name__)
T = TypeVar("T")


class TypesetError(RuntimeError):
    pass


class Busy(Exception):
    """Too many requests are already waiting for a work slot."""


class Gate:
    """Limits concurrent work to a fixed number of slots and bounds the queue behind them.

    A semaphore alone queues without limit, so a burst makes every request slow and the process holds
    them all. Past `max_waiting` queued requests, new ones fail fast with Busy (HTTP 503), which a proxy
    or browser can retry, while the occupied slots keep working at full speed."""

    def __init__(self, slots: int, max_waiting: int) -> None:
        self._sem = asyncio.Semaphore(slots)
        self.max_waiting = max_waiting
        self.waiting = 0

    async def __aenter__(self) -> None:
        if self._sem.locked() and self.waiting >= self.max_waiting:
            raise Busy()
        self.waiting += 1
        try:
            await self._sem.acquire()
        finally:
            self.waiting -= 1

    async def __aexit__(self, *exc) -> None:
        self._sem.release()


class Aborted(Exception):
    """The client went away while waiting its turn, so no work was started."""


async def finish(
    proc: asyncio.subprocess.Process,
    timeout_s: float,
    abort: Callable[[], Awaitable[bool]] | None = None,
) -> tuple[bytes, bytes]:
    """Wait for a Typst process and return (stdout, stderr). If the client leaves mid-render, the
    time runs out, or this task is cancelled, kill the process: an abandoned render must not keep a
    core busy, and a process must never be left for the garbage collector to find. Every wait on a
    Typst process goes through here."""
    pending = asyncio.ensure_future(proc.communicate())
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=0.1)
            if done:
                return pending.result()
            if time.monotonic() > deadline:
                raise TypesetError("Typesetting timed out")
            if abort is not None and await abort():
                raise Aborted()
    except BaseException:
        pending.cancel()
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise


async def _compile(
    data: dict,
    settings: Settings,
    gate: asyncio.Semaphore,
    args: list[str],
    output: str,
    collect: Callable[[Path], T],
    abort: Callable[[], Awaitable[bool]] | None,
    source: str | None = None,
) -> T:
    template = (
        source
        if source is not None
        else (
            resources.files("manuscript_discovery")
            .joinpath("template/book.typ")
            .read_text("utf-8")
        )
    )
    async with gate:
        if (
            abort is not None and await abort()
        ):  # cheap, and sheds stale queued previews
            raise Aborted()
        with tempfile.TemporaryDirectory(prefix="md-") as td:
            work = Path(td)
            (work / "book.typ").write_text(template, "utf-8")
            (work / "data.json").write_text(
                json.dumps(data, ensure_ascii=False), "utf-8"
            )
            cmd = [
                settings.typst_bin,
                "compile",
                "--root",
                td,
                "--diagnostic-format",
                "short",
                *args,
            ]
            if settings.typst_jobs is not None:
                cmd += ["--jobs", str(settings.typst_jobs)]
            if settings.font_dir:
                cmd += ["--ignore-system-fonts", "--font-path", str(settings.font_dir)]
            cmd += [str(work / "book.typ"), str(work / output)]
            env = {"PATH": os.environ.get("PATH", ""), "HOME": td, "TMPDIR": td}
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=td,
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as e:
                raise TypesetError(
                    f"Typst executable not found: {settings.typst_bin}"
                ) from e
            text = (await finish(proc, settings.timeout_s, abort))[1].decode(
                "utf-8", "replace"
            )
            if proc.returncode != 0:
                log.error("typst failed (%s): %s", proc.returncode, text[:2000])
                raise TypesetError("Typesetting failed")
            if (
                "unknown font family" in text
            ):  # not fatal: the output uses a fallback font
                log.warning("typst: %s", text.strip().splitlines()[0])
            return collect(work)


async def render_pdf(
    data: dict,
    settings: Settings,
    gate: asyncio.Semaphore,
    abort: Callable[[], Awaitable[bool]] | None = None,
) -> bytes:
    return await _compile(
        data,
        settings,
        gate,
        ["--format", "pdf"],
        "out.pdf",
        lambda w: (w / "out.pdf").read_bytes(),
        abort,
    )


async def render_png(
    data: dict,
    settings: Settings,
    gate: asyncio.Semaphore,
    abort: Callable[[], Awaitable[bool]] | None = None,
) -> list[bytes]:
    """Low-resolution page images for on-screen preview. Renders one page more than the preview
    shows, so the caller can tell whether the document continues."""
    args = [
        "--format",
        "png",
        "--ppi",
        str(settings.preview_ppi),
        "--pages",
        f"1-{settings.preview_pages + 1}",
    ]
    return await _compile(
        data,
        settings,
        gate,
        args,
        "out-{0p}.png",
        lambda w: [f.read_bytes() for f in sorted(w.glob("out-*.png"))],
        abort,
    )

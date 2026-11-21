"""Run Typst on a document. Scripture text travels as JSON data, never as Typst source,
so no escaping is needed and the text cannot inject markup or file access."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from importlib import resources
from pathlib import Path

from .settings import Settings

log = logging.getLogger(__name__)


class TypesetError(RuntimeError):
    pass


async def render_pdf(data: dict, settings: Settings, gate: asyncio.Semaphore) -> bytes:
    template = (
        resources.files("bible_typeset")
        .joinpath("template/book.typ")
        .read_text("utf-8")
    )
    async with gate, _tempdir() as work:
        (work / "book.typ").write_text(template, "utf-8")
        (work / "data.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        cmd = [
            settings.typst_bin,
            "compile",
            "--root",
            str(work),
            "--diagnostic-format",
            "short",
        ]
        if settings.font_dir:
            cmd += ["--ignore-system-fonts", "--font-path", str(settings.font_dir)]
        cmd += [str(work / "book.typ"), str(work / "out.pdf")]
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(work),
            "TMPDIR": str(work),
        }
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=work,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise TypesetError(
                f"Typst executable not found: {settings.typst_bin}"
            ) from e
        try:
            _, err = await asyncio.wait_for(proc.communicate(), settings.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TypesetError("Typesetting timed out") from None
        text = err.decode("utf-8", "replace")
        if proc.returncode != 0:
            log.error("typst failed (%s): %s", proc.returncode, text[:2000])
            raise TypesetError("Typesetting failed")
        if (
            "unknown font family" in text
        ):  # not fatal, but the output will use a fallback
            log.warning("typst: %s", text.strip().splitlines()[0])
        return (work / "out.pdf").read_bytes()


class _tempdir:
    """Async-friendly TemporaryDirectory yielding a Path."""

    async def __aenter__(self) -> Path:
        self._td = tempfile.TemporaryDirectory(prefix="bible-")
        return Path(self._td.name)

    async def __aexit__(self, *exc) -> None:
        self._td.cleanup()

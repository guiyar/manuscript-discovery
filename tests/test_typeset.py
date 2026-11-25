import asyncio
import gc
import os
import stat
import time
import warnings

import pytest

from manuscript_discovery.settings import Settings
from manuscript_discovery.typeset import Aborted, TypesetError, render_png


def run(coro):
    return asyncio.run(coro)


def test_a_client_that_left_while_queued_costs_nothing():
    async def gone():
        return True

    # If Typst were started this would raise TypesetError (no such executable); Aborted proves it was not.
    with pytest.raises(Aborted):
        run(
            render_png(
                {},
                Settings(typst_bin="/nonexistent/typst"),
                asyncio.Semaphore(1),
                abort=gone,
            )
        )


def test_a_client_still_waiting_is_served():
    async def here():
        return False

    with pytest.raises(TypesetError, match="not found"):
        run(
            render_png(
                {},
                Settings(typst_bin="/nonexistent/typst"),
                asyncio.Semaphore(1),
                abort=here,
            )
        )


def slow_typst(tmp_path):
    """A stand-in for typst that records its pid and then takes 30 s."""
    pidfile = tmp_path / "pid"
    script = tmp_path / "typst"
    script.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nexec sleep 30\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, pidfile


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_typst_is_killed_when_the_client_leaves_mid_render(tmp_path):
    script, pidfile = slow_typst(tmp_path)
    calls = iter([False, False, True])  # still here at the start, gone a moment later

    async def abort():
        return next(calls, True)

    started = time.monotonic()
    with pytest.raises(Aborted):
        run(
            render_png(
                {}, Settings(typst_bin=str(script)), asyncio.Semaphore(1), abort=abort
            )
        )
    assert time.monotonic() - started < 5
    time.sleep(0.2)
    assert not alive(int(pidfile.read_text()))  # no orphan keeps a core busy


def test_typst_is_killed_when_the_request_is_cancelled(tmp_path):
    script, pidfile = slow_typst(tmp_path)

    async def scenario():
        task = asyncio.create_task(
            render_png({}, Settings(typst_bin=str(script)), asyncio.Semaphore(1))
        )
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    time.sleep(0.2)
    assert not alive(int(pidfile.read_text()))


def test_a_render_that_takes_too_long_is_killed(tmp_path):
    script, pidfile = slow_typst(tmp_path)
    with pytest.raises(TypesetError, match="timed out"):
        run(
            render_png(
                {}, Settings(typst_bin=str(script), timeout_s=0.5), asyncio.Semaphore(1)
            )
        )
    time.sleep(0.2)
    assert not alive(int(pidfile.read_text()))


def leaked_processes(marker: str) -> list[int]:
    """Live processes whose command line contains the marker (read from /proc, Linux only)."""
    pids = []
    for entry in os.scandir("/proc"):
        if entry.name.isdigit():
            try:
                with open(f"/proc/{entry.name}/cmdline", "rb") as f:
                    if marker.encode() in f.read():
                        pids.append(int(entry.name))
            except OSError:
                pass
    return pids


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="needs /proc")
def test_cancelling_at_any_moment_never_leaves_typst_running(tmp_path):
    """Including the few milliseconds while the process is still starting, when there is no handle yet."""
    marker = f"sleep {os.getpid()}.5"  # unique to this test run
    script = tmp_path / "typst"
    script.write_text(f"#!/bin/sh\nexec {marker}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    async def scenario(delay):
        task = asyncio.create_task(
            render_png({}, Settings(typst_bin=str(script)), asyncio.Semaphore(1))
        )
        await asyncio.sleep(delay)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    for delay in (0, 0.0005, 0.001, 0.002, 0.004, 0.008, 0.016, 0.03, 0.06):
        for _ in range(4):
            run(scenario(delay))
    time.sleep(0.3)
    assert leaked_processes(marker) == [], (
        "a Typst process outlived its cancelled request"
    )


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="needs /proc")
def test_cancelling_the_startup_font_check_leaves_nothing_running(tmp_path):
    """The self-test runs in the background and is cancelled at shutdown, possibly mid-run."""
    from manuscript_discovery import diagnostics

    marker = f"sleep {os.getpid()}.7"
    script = tmp_path / "typst"
    script.write_text(
        f"#!/bin/sh\nexec {marker}\n"
    )  # takes a long time whatever it is asked
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    async def scenario():
        task = asyncio.create_task(diagnostics.run(Settings(typst_bin=str(script))))
        await asyncio.sleep(0.4)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Garbage left by earlier tests (an unclosed database, say) is collected whenever any test
    # next calls gc.collect(). Settle it first, then judge only the warnings asyncio raises
    # about an abandoned process, so this test fails for its own leaks and no one else's.
    gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run(scenario())
        gc.collect()  # an abandoned process transport would complain here
    abandoned = [
        str(w.message)
        for w in caught
        if "subprocess" in str(w.message) or "transport" in str(w.message)
    ]
    assert abandoned == []
    time.sleep(0.3)
    assert leaked_processes(marker) == []


def test_configured_typst_jobs_are_passed_to_compiler(tmp_path):
    import json
    import sys

    script = tmp_path / "typst"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[-1].replace('{0p}', '1')).write_text(json.dumps(sys.argv))\n"
    )
    script.chmod(0o700)
    for jobs in (None, 2):
        pages = run(render_png({}, Settings(typst_bin=str(script), typst_jobs=jobs), asyncio.Semaphore(1)))
        args = json.loads(pages[0])
        if jobs is None:
            assert "--jobs" not in args
        else:
            assert args[args.index("--jobs") + 1] == str(jobs)


def test_output_bounds(tmp_path):
    from manuscript_discovery.typeset import read_bounded, read_pages

    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"1234")
    assert read_bounded(pdf, 4) == b"1234"
    with pytest.raises(TypesetError, match="size limit"):
        read_bounded(pdf, 3)
    for i in (1, 2):
        (tmp_path / f"out-{i}.png").write_bytes(b"1234")
    assert read_pages(tmp_path, 8, 2) == [b"1234", b"1234"]
    with pytest.raises(TypesetError, match="size limit"):
        read_pages(tmp_path, 7, 2)
    with pytest.raises(TypesetError, match="number"):
        read_pages(tmp_path, 8, 1)


def test_diagnostic_streams_are_drained_but_bounded():
    import sys
    from manuscript_discovery.typeset import finish

    async def scenario():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import sys; sys.stdout.buffer.write(b'x'*1000000); sys.stderr.buffer.write(b'y'*1000000)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await finish(proc, 5)
        assert proc.returncode == 0
        assert out == b"x" * 65536 and err == b"y" * 65536

    run(scenario())

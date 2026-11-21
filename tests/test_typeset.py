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

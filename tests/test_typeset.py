import asyncio
import os
import stat
import time

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

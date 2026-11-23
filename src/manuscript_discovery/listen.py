"""Listening on a Unix socket, created with exactly the permissions we choose.

uvicorn's own `uds` option chmods the socket to 0666 after binding, which leaves it world-writable
whatever the umask. So the app binds the socket itself and hands the bound socket to uvicorn.
"""

import os
import socket
import stat
from pathlib import Path

SOCKET_MODE = 0o660  # owner and group, nobody else


def bind_unix_socket(path: Path, mode: int = SOCKET_MODE) -> socket.socket:
    """Bind a stream socket at `path`, created with exactly `mode` (no moment when it is more open).

    A stale socket file from a previous run is replaced. A live one (another process listening)
    or anything that is not a socket is refused, never overwritten.
    """
    path = Path(path)
    if not path.parent.is_dir():
        raise FileNotFoundError(
            f"{path.parent} does not exist (systemd's RuntimeDirectory= creates it)"
        )
    _remove_if_stale(path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous = os.umask(0o777 & ~mode)  # the file is born with `mode`
    try:
        sock.bind(str(path))
    except BaseException:
        sock.close()
        raise
    finally:
        os.umask(previous)
    return sock


def _remove_if_stale(path: Path) -> None:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(st.st_mode):
        raise FileExistsError(
            f"{path} exists and is not a socket; refusing to remove it"
        )
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError):
        path.unlink(missing_ok=True)  # nobody is listening: left over from a crash
    else:
        raise OSError(f"another process is already listening on {path}")
    finally:
        probe.close()

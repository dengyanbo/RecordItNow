"""Single-instance enforcement.

RIN is a tray application: a second instance would attach a duplicate
icon, register a duplicate global hotkey listener, and race the same
SQLite database file. To keep things deterministic we hold an
OS-level exclusive lock on ``<data_dir>\\.lock`` for the lifetime of
the process. The lock is held by an open file handle; closing the
process (cleanly or via crash) releases it automatically, so we never
need stale-lock cleanup logic.

The lock is intentionally per-user: the data directory is per-user, so
two different users can run RIN side-by-side on a shared machine
without stepping on each other.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .logging import get_logger

log = get_logger(__name__)

_lock_handle = None
_lock_path: Path | None = None


def _try_msvcrt_lock(handle) -> bool:
    """Acquire a non-blocking exclusive lock via ``msvcrt`` (Windows)."""

    try:
        import msvcrt
    except ImportError:
        return False
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _try_fcntl_lock(handle) -> bool:
    """Acquire a non-blocking exclusive lock via ``fcntl`` (POSIX)."""

    try:
        import fcntl
    except ImportError:
        return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def acquire(lock_path: Path | None = None) -> bool:
    """Acquire the singleton lock.

    Returns ``True`` if this process is now the sole RIN instance for
    the current user, ``False`` if another instance is already
    running. ``lock_path`` is exposed mainly for testing; in normal use
    the caller passes nothing and the path is derived from
    :func:`rin.paths.root_dir`.
    """

    global _lock_handle, _lock_path
    if _lock_handle is not None:
        return True

    if lock_path is None:
        from .. import paths

        lock_path = paths.root_dir() / ".lock"
    _lock_path = lock_path
    _lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Open in append/binary so we never accidentally truncate stale
    # diagnostics another user might want to inspect. The handle is
    # deliberately kept open for the process lifetime — closing it
    # would release the lock — so context-manager use is not
    # appropriate here.
    handle = open(_lock_path, "ab+")  # noqa: SIM115 — long-lived by design
    locked = _try_msvcrt_lock(handle) or _try_fcntl_lock(handle)
    if not locked:
        handle.close()
        _lock_handle = None
        log.warning(
            f"Could not acquire singleton lock at {_lock_path} — another "
            "RIN instance is already running"
        )
        return False

    # Stamp the lock file with our pid for diagnostics. Best-effort.
    try:
        handle.seek(0)
        handle.truncate(0)
        handle.write(f"{os.getpid()}\n".encode())
        handle.flush()
    except OSError:
        pass

    _lock_handle = handle
    log.debug(f"Acquired singleton lock at {_lock_path} (pid={os.getpid()})")
    return True


def release() -> None:
    """Release the singleton lock if held. Idempotent."""

    global _lock_handle
    if _lock_handle is None:
        return
    try:
        _lock_handle.close()
    finally:
        _lock_handle = None
        log.debug("Released singleton lock")


def notify_already_running() -> None:
    """Show a best-effort Windows MessageBox.

    Called when ``acquire()`` returns ``False``. Falls back to a plain
    stderr write if the MessageBox API is unavailable (non-Windows /
    headless test runners). Never raises; the goal is to make the
    second-instance exit visible to the user, not to halt on UI errors.

    Set ``RIN_SUPPRESS_DUP_DIALOG=1`` to skip the modal (used by
    automated tests and unattended launchers that just want a silent
    exit).
    """

    msg = (
        "RIN is already running. Look for the RIN icon in your system tray "
        "(bottom-right), or use the tray menu to quit the existing instance "
        "before starting a new one."
    )
    title = "RIN — Already running"

    if os.environ.get("RIN_SUPPRESS_DUP_DIALOG") == "1":
        if sys.stderr is not None:
            print(f"{title}: {msg}", file=sys.stderr)
        return

    if sys.platform == "win32":
        try:
            import ctypes

            mb_ok = 0x0
            mb_icon_information = 0x40
            mb_setforeground = 0x10000
            ctypes.windll.user32.MessageBoxW(
                0, msg, title, mb_ok | mb_icon_information | mb_setforeground
            )
            return
        except Exception:  # noqa: BLE001 — UI is best-effort
            pass

    if sys.stderr is not None:
        print(f"{title}: {msg}", file=sys.stderr)

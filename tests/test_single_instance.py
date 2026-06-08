"""Tests for the single-instance lock."""
from __future__ import annotations

from pathlib import Path

from rin.utils import single_instance


def test_acquire_returns_true_when_no_other_instance(tmp_path: Path) -> None:
    lock = tmp_path / ".lock"
    try:
        assert single_instance.acquire(lock_path=lock) is True
        assert lock.exists()
    finally:
        single_instance.release()


def test_acquire_is_idempotent_for_same_process(tmp_path: Path) -> None:
    lock = tmp_path / ".lock"
    try:
        assert single_instance.acquire(lock_path=lock) is True
        # Calling acquire again from the same process should be a no-op
        # and still report we hold the lock.
        assert single_instance.acquire(lock_path=lock) is True
    finally:
        single_instance.release()


def test_release_is_idempotent(tmp_path: Path) -> None:
    lock = tmp_path / ".lock"
    assert single_instance.acquire(lock_path=lock) is True
    single_instance.release()
    # Releasing again must not raise.
    single_instance.release()


def test_second_acquire_after_release_succeeds(tmp_path: Path) -> None:
    lock = tmp_path / ".lock"
    assert single_instance.acquire(lock_path=lock) is True
    single_instance.release()
    # Same path, fresh acquire after release: lock is free again.
    try:
        assert single_instance.acquire(lock_path=lock) is True
    finally:
        single_instance.release()


def test_concurrent_external_lock_blocks_acquire(tmp_path: Path) -> None:
    """Simulate another process holding the lock and confirm we bail.

    We grab the lock from a separate file handle (still in this
    process — different fd), which is enough on both Windows
    ``msvcrt`` and POSIX ``fcntl`` to make our acquire() fail.
    """
    import sys

    lock = tmp_path / ".lock"
    # Create + hold an exclusive lock on the file via a fresh handle.
    # The handle must survive the assertion (lock release on close)
    # so we deliberately do not use a context manager here.
    holder = open(lock, "ab+")  # noqa: SIM115
    held = False
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
                held = True
            except OSError:
                pass
        else:
            try:
                import fcntl

                fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
            except (OSError, ImportError):
                pass

        if not held:
            # On platforms where we cannot hold the lock from another fd
            # in the same process (rare), skip the assertion.
            return

        assert single_instance.acquire(lock_path=lock) is False
    finally:
        # Reset to a known state — undo any bookkeeping the helper
        # may have stashed even though it returned False.
        single_instance.release()
        try:
            if sys.platform == "win32":
                import contextlib
                import msvcrt

                holder.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            holder.close()

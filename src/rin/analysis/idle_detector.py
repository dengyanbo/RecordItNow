"""Idle-detection: how long since the user last touched their keyboard/mouse.

Uses Windows' ``GetLastInputInfo`` API. On non-Windows hosts the
detector returns 0 seconds (i.e. "not idle") so tests run anywhere.
"""
from __future__ import annotations

import sys

from ..utils.logging import get_logger

log = get_logger(__name__)


def get_idle_seconds() -> float:
    """Seconds since the user last touched the keyboard or mouse."""

    if sys.platform != "win32":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover - Windows-only path
        return 0.0

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        log.debug("GetLastInputInfo failed; assuming not idle")
        return 0.0
    millis = kernel32.GetTickCount() - info.dwTime
    return max(0.0, millis / 1000.0)


def is_idle(threshold_seconds: float) -> bool:
    return get_idle_seconds() >= threshold_seconds

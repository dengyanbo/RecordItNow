"""Manage autostart through platform-specific compatibility dispatchers."""
from __future__ import annotations

from . import _platform_windows, platform_compat

RUN_KEY = _platform_windows.RUN_KEY
VALUE_NAME = _platform_windows.VALUE_NAME

# Kept for backwards-compatible tests that monkeypatch ``rin.utils.autostart._winreg``.
_winreg = _platform_windows._winreg


def _call_with_synced_winreg(callback, *args, **kwargs):
    original = _platform_windows._winreg
    _platform_windows._winreg = _winreg
    try:
        return callback(*args, **kwargs)
    finally:
        _platform_windows._winreg = original


def is_enabled() -> bool:
    return _call_with_synced_winreg(_platform_windows.is_autostart_enabled)


def enable(command: str) -> bool:
    """Set the autostart entry to ``command``. Returns True on success."""

    return _call_with_synced_winreg(platform_compat.enable_autostart, command)


def disable() -> bool:
    return _call_with_synced_winreg(platform_compat.disable_autostart)


def default_command() -> str:
    """Return the most sensible ``rin`` invocation for the current install."""

    return _platform_windows.default_autostart_command()

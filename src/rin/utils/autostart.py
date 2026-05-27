"""Manage Windows "run at login" autostart via the ``Run`` registry key.

The current-user ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
key is used so RIN doesn't require admin to enable/disable. On non-Windows
hosts every function is a no-op so we can import this module from tests
anywhere.
"""
from __future__ import annotations

import sys

from ..utils.logging import get_logger

log = get_logger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "RIN"


def _winreg():
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore[import]
    except ImportError:  # pragma: no cover - Windows-only
        return None
    return winreg


def is_enabled() -> bool:
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning(f"autostart.is_enabled query failed: {exc}")
        return False


def enable(command: str) -> bool:
    """Set the Run key value to ``command``. Returns True on success."""

    winreg = _winreg()
    if winreg is None:
        log.warning("autostart.enable: not on Windows")
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        log.info(f"Autostart enabled: {command}")
        return True
    except OSError as exc:
        log.error(f"autostart.enable failed: {exc}")
        return False


def disable() -> bool:
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                return True
        log.info("Autostart disabled")
        return True
    except OSError as exc:
        log.error(f"autostart.disable failed: {exc}")
        return False


def default_command() -> str:
    """Return the most sensible ``rin`` invocation for the current install."""

    if sys.platform != "win32":
        return f'"{sys.executable}" -m rin'
    # Prefer a frozen exe (``rin.exe`` next to python.exe in the venv) if present.
    from pathlib import Path

    candidate = Path(sys.executable).parent / "rin.exe"
    if candidate.exists():
        return f'"{candidate}"'
    return f'"{sys.executable}" -m rin'

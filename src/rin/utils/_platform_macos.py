"""Import-safe macOS stubs for :mod:`rin.utils.platform_compat`."""
from __future__ import annotations

import importlib
from typing import Literal

from .logging import get_logger

log = get_logger(__name__)

ThemeName = Literal["light", "dark"]

try:  # pragma: no cover - depends on host environment
    _appkit = importlib.import_module("AppKit")
except ImportError as exc:  # pragma: no cover - exercised on Windows/Linux hosts
    _appkit = None
    log.debug(f"macOS AppKit stubs active: {exc}")


def list_audio_devices(binary: str = "ffmpeg", runner=None) -> list[str]:
    """Return ``[]`` until a future macOS port enumerates CoreAudio devices."""

    _ = (binary, runner)
    return []


def get_system_theme() -> ThemeName:
    """Return ``"light"`` until NSUserDefaults is used to read AppleInterfaceStyle."""

    return "light"


def enable_autostart(command: str) -> bool:
    """Return ``False`` until we manage a LaunchAgent plist in ``~/Library/LaunchAgents``."""

    _ = command
    return False


def disable_autostart() -> bool:
    """Return ``False`` until the macOS LaunchAgent-based autostart exists."""

    return False


def get_foreground_window_title() -> str:
    """Return ``""`` until NSWorkspace + Accessibility APIs can inspect the front window."""

    return ""


def get_foreground_process_name() -> str:
    """Return ``""`` until NSWorkspace is used for the frontmost app name."""

    return ""


__all__ = [
    "disable_autostart",
    "enable_autostart",
    "get_foreground_process_name",
    "get_foreground_window_title",
    "get_system_theme",
    "list_audio_devices",
]

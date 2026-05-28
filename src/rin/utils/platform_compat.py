"""Cross-platform dispatchers for platform-specific helpers."""
from __future__ import annotations

import sys
from typing import Literal

from . import _platform_linux, _platform_macos, _platform_windows

ThemeName = Literal["light", "dark"]


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def _platform_module():
    if is_windows():
        return _platform_windows
    if is_macos():
        return _platform_macos
    return _platform_linux


def list_audio_devices(binary: str = "ffmpeg", runner=None) -> list[str]:
    """Return platform-specific audio device names safe to import on any OS."""

    return _platform_module().list_audio_devices(binary=binary, runner=runner)


def get_system_theme() -> ThemeName:
    """Return the current platform theme preference, defaulting to ``"light"``."""

    return _platform_module().get_system_theme()


def enable_autostart(command: str) -> bool:
    """Enable autostart on the current platform, if supported."""

    return _platform_module().enable_autostart(command)


def disable_autostart() -> bool:
    """Disable autostart on the current platform, if supported."""

    return _platform_module().disable_autostart()


def get_foreground_window_title() -> str:
    """Return the current foreground window title, or ``""`` when unavailable."""

    return _platform_module().get_foreground_window_title()


def get_foreground_process_name() -> str:
    """Return the current foreground process name, or ``""`` when unavailable."""

    return _platform_module().get_foreground_process_name()


__all__ = [
    "disable_autostart",
    "enable_autostart",
    "get_foreground_process_name",
    "get_foreground_window_title",
    "get_system_theme",
    "is_linux",
    "is_macos",
    "is_windows",
    "list_audio_devices",
]

"""Import-safe Linux stubs for :mod:`rin.utils.platform_compat`."""
from __future__ import annotations

import importlib
from typing import Literal

from .logging import get_logger

log = get_logger(__name__)

ThemeName = Literal["light", "dark"]

try:  # pragma: no cover - depends on host environment
    _gi = importlib.import_module("gi")
except ImportError as exc:  # pragma: no cover - exercised on Windows/macOS hosts
    _gi = None
    log.debug(f"Linux desktop stubs active: {exc}")


def list_audio_devices(binary: str = "ffmpeg", runner=None) -> list[str]:
    """Return ``[]`` until we enumerate PulseAudio or PipeWire capture devices."""

    _ = (binary, runner)
    return []


def get_system_theme() -> ThemeName:
    """Return ``"light"`` until GTK Settings or XDG portals expose a desktop theme."""

    return "light"


def enable_autostart(command: str) -> bool:
    """Return ``False`` until we manage a ``~/.config/autostart/*.desktop`` entry."""

    _ = command
    return False


def disable_autostart() -> bool:
    """Return ``False`` until the Linux ``.desktop`` autostart flow exists."""

    return False


def get_foreground_window_title() -> str:
    """Return ``""`` until X11 or Wayland APIs can report the active window title."""

    return ""


def get_foreground_process_name() -> str:
    """Return ``""`` until X11 or Wayland APIs can report the active process."""

    return ""


__all__ = [
    "disable_autostart",
    "enable_autostart",
    "get_foreground_process_name",
    "get_foreground_window_title",
    "get_system_theme",
    "list_audio_devices",
]

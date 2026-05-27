"""Global "panic pause" hotkey: Ctrl+Alt+Shift+P toggles capture pause.

Implemented with the ``keyboard`` package, which registers OS-level
hotkeys on Windows without needing focus. A missing dependency or
permission error degrades to a no-op (and a warning) rather than
crashing the tray.
"""
from __future__ import annotations

from collections.abc import Callable

from ..utils.logging import get_logger

log = get_logger(__name__)

DEFAULT_HOTKEY = "ctrl+alt+shift+p"


class PanicHotkey:
    """Wraps the ``keyboard`` library so the rest of the app doesn't depend on it."""

    def __init__(self, callback: Callable[[], None], *, hotkey: str = DEFAULT_HOTKEY) -> None:
        self.callback = callback
        self.hotkey = hotkey
        self._registered = False
        self._handle = None

    def install(self) -> bool:
        try:
            import keyboard  # type: ignore[import]
        except ImportError:
            log.warning("keyboard package unavailable; panic hotkey disabled")
            return False
        try:
            self._handle = keyboard.add_hotkey(self.hotkey, self._invoke)
            self._registered = True
            log.info(f"Panic hotkey installed: {self.hotkey}")
            return True
        except Exception as exc:
            log.warning(f"Failed to install panic hotkey: {exc}")
            return False

    def uninstall(self) -> None:
        if not self._registered:
            return
        try:
            import keyboard  # type: ignore[import]

            keyboard.remove_hotkey(self._handle or self.hotkey)
        except Exception as exc:
            log.warning(f"Failed to remove panic hotkey: {exc}")
        self._registered = False
        self._handle = None

    def _invoke(self) -> None:
        try:
            self.callback()
        except Exception as exc:
            log.error(f"Panic hotkey callback raised: {exc}")

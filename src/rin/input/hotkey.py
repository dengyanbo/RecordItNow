r"""Keyboard + mouse listeners backed by ``pynput``.

Both listeners run their own background threads (managed by pynput) and
push :class:`InputEvent`\ s through the shared callback. The callback
must be thread-safe; the manager bridges to Qt by emitting a queued
signal.
"""
from __future__ import annotations

from ..utils.logging import get_logger
from .base import EventCallback, InputEvent, ListenerBase

log = get_logger(__name__)


def _key_name(key) -> str:
    """Return a stable lower-case identifier for a pynput key."""

    char = getattr(key, "char", None)
    if char:
        return str(char).lower()
    name = getattr(key, "name", None)
    if name:
        return str(name).lower()
    return repr(key).lower()


def _mouse_button_name(button) -> str:
    name = getattr(button, "name", None) or str(button)
    return name.split(".")[-1].lower()


class KeyboardListener(ListenerBase):
    def __init__(self, callback: EventCallback) -> None:
        super().__init__(callback)
        self._listener = None

    def start(self) -> None:
        if self._running:
            return
        try:
            from pynput import keyboard
        except ImportError as exc:  # pragma: no cover
            log.warning(f"pynput not available: {exc}")
            return

        def _on_press(key) -> None:
            self.emit(
                InputEvent(
                    kind="press",
                    source="keyboard",
                    identifier=_key_name(key),
                    timestamp_ms=InputEvent.now_ms(),
                )
            )

        def _on_release(key) -> None:
            self.emit(
                InputEvent(
                    kind="release",
                    source="keyboard",
                    identifier=_key_name(key),
                    timestamp_ms=InputEvent.now_ms(),
                )
            )

        self._listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
        self._listener.start()
        self._running = True
        log.info("Keyboard listener started")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._running = False


class MouseListener(ListenerBase):
    def __init__(self, callback: EventCallback) -> None:
        super().__init__(callback)
        self._listener = None

    def start(self) -> None:
        if self._running:
            return
        try:
            from pynput import mouse
        except ImportError as exc:  # pragma: no cover
            log.warning(f"pynput not available: {exc}")
            return

        def _on_click(_x, _y, button, pressed) -> None:
            self.emit(
                InputEvent(
                    kind="press" if pressed else "release",
                    source="mouse",
                    identifier=_mouse_button_name(button),
                    timestamp_ms=InputEvent.now_ms(),
                )
            )

        self._listener = mouse.Listener(on_click=_on_click)
        self._listener.start()
        self._running = True
        log.info("Mouse listener started")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._running = False

"""Manager that owns listeners + recognizer and bridges them to Qt's event loop.

Listeners run in background threads (pynput / hidapi). Their callback
fires on those threads; we forward the event through a queued Qt signal
so the recognizer and downstream slots execute on the main thread.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from ..config import RinConfig, TriggerBinding
from ..utils.logging import get_logger
from .base import InputEvent
from .gesture import GestureRecognizer
from .hid_listener import HIDListener
from .hotkey import KeyboardListener, MouseListener
from .learn_mode import LearnRecorder

log = get_logger(__name__)


class InputManager(QObject):
    """Owns the listeners + recognizer. One instance per running app."""

    # Re-exported for callers who don't want to fish out the recognizer.
    shot_requested = Signal()
    record_started = Signal()
    record_stopped = Signal()

    # Internal: thread-safe relay from listener threads onto the Qt main thread.
    _event_received = Signal(InputEvent)

    def __init__(self, config: RinConfig, *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._recognizer = GestureRecognizer(config.trigger, parent=self)
        self._recognizer.shot_requested.connect(self.shot_requested)
        self._recognizer.record_started.connect(self.record_started)
        self._recognizer.record_stopped.connect(self.record_stopped)

        # Queued connection guarantees event dispatch happens on the manager's owning thread.
        self._event_received.connect(self._dispatch_event, Qt.QueuedConnection)

        self._keyboard = KeyboardListener(self._post_event)
        self._mouse = MouseListener(self._post_event)
        self._hid: HIDListener | None = None
        self._learn: LearnRecorder | None = None
        self._paused = config.paused

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        log.info("InputManager starting")
        self._keyboard.start()
        self._mouse.start()
        self._reconfigure_hid()

    def stop(self) -> None:
        log.info("InputManager stopping")
        self._keyboard.stop()
        self._mouse.stop()
        if self._hid is not None:
            self._hid.stop()
            self._hid = None

    # --- public API ---------------------------------------------------------------

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        log.info(f"InputManager paused={paused}")

    def is_paused(self) -> bool:
        return self._paused

    def update_binding(self, binding: TriggerBinding) -> None:
        self._config.trigger = binding
        self._recognizer.set_binding(binding)
        self._reconfigure_hid()

    def start_learn(
        self,
        *,
        hold_threshold_ms: int | None = None,
        on_captured: Callable[[TriggerBinding], None] | None = None,
    ) -> LearnRecorder:
        threshold = hold_threshold_ms or self._config.trigger.hold_threshold_ms
        self._learn = LearnRecorder(
            hold_threshold_ms=threshold,
            on_captured=lambda b: self._on_learn_captured(b, on_captured),
        )
        return self._learn

    def cancel_learn(self) -> None:
        self._learn = None

    # --- internals ----------------------------------------------------------------

    def _post_event(self, event: InputEvent) -> None:
        # Called from listener threads; relay via queued signal.
        self._event_received.emit(event)

    def _dispatch_event(self, event: InputEvent) -> None:
        if self._learn is not None:
            self._learn.handle_event(event)
            if self._learn.captured is not None:
                self._learn = None
            return
        if self._paused:
            return
        self._recognizer.handle_event(event)

    def _on_learn_captured(
        self,
        binding: TriggerBinding,
        callback: Callable[[TriggerBinding], None] | None,
    ) -> None:
        self.update_binding(binding)
        if callback is not None:
            callback(binding)

    def _reconfigure_hid(self) -> None:
        if self._hid is not None:
            self._hid.stop()
            self._hid = None
        b = self._config.trigger
        if (
            b.source == "hid"
            and b.vendor_id is not None
            and b.product_id is not None
        ):
            self._hid = HIDListener(
                self._post_event,
                vendor_id=b.vendor_id,
                product_id=b.product_id,
                usage_page=b.usage_page,
                usage=b.usage,
            )
            self._hid.start()

"""Gesture recognition: pure state machine + Qt wrapper.

Design split
------------
:class:`GestureStateMachine` is a pure-Python state machine with no Qt
dependency. It takes ``on_press(now_ms)``, ``on_release(now_ms)``, and
``tick(now_ms)`` calls, and returns the events it wants to emit. This
makes unit tests trivial.

:class:`GestureRecognizer` is a thin ``QObject`` wrapper that listens to
``InputEvent`` callbacks, schedules a one-shot ``QTimer`` for the hold
threshold, and forwards state-machine outputs as Qt signals.

Gestures
--------
* **Tap**  — press, release before ``hold_threshold_ms`` → ``shot_requested``.
* **Hold** — press, no release after ``hold_threshold_ms`` → ``record_started``;
  release at any later time → ``record_stopped``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import TriggerBinding
from ..utils.logging import get_logger
from .base import InputEvent, binding_matches_event

log = get_logger(__name__)


class GestureState(Enum):
    IDLE = "idle"
    PRESSED = "pressed"
    RECORDING = "recording"


@dataclass
class GestureEmit:
    """A single output event from the state machine."""

    kind: Literal["shot", "record_start", "record_stop"]


class GestureStateMachine:
    """Pure-Python gesture recognizer. Time arguments are arbitrary monotonic ms."""

    def __init__(self, hold_threshold_ms: int = 500) -> None:
        self.hold_threshold_ms = hold_threshold_ms
        self._state = GestureState.IDLE
        self._press_time_ms: float | None = None

    @property
    def state(self) -> GestureState:
        return self._state

    def reset(self) -> None:
        self._state = GestureState.IDLE
        self._press_time_ms = None

    def on_press(self, now_ms: float) -> list[GestureEmit]:
        if self._state != GestureState.IDLE:
            # Already pressed — ignore repeat presses (e.g. key auto-repeat).
            return []
        self._state = GestureState.PRESSED
        self._press_time_ms = now_ms
        return []

    def on_release(self, now_ms: float) -> list[GestureEmit]:
        if self._state == GestureState.PRESSED:
            assert self._press_time_ms is not None
            duration = now_ms - self._press_time_ms
            self.reset()
            if duration < self.hold_threshold_ms:
                return [GestureEmit("shot")]
            # A press long enough to be a hold but no tick fired (clock jitter).
            return [GestureEmit("record_start"), GestureEmit("record_stop")]
        if self._state == GestureState.RECORDING:
            self.reset()
            return [GestureEmit("record_stop")]
        return []

    def tick(self, now_ms: float) -> list[GestureEmit]:
        """Called when the hold timer fires. Returns ``record_start`` if still pressed."""

        if self._state != GestureState.PRESSED or self._press_time_ms is None:
            return []
        if now_ms - self._press_time_ms >= self.hold_threshold_ms:
            self._state = GestureState.RECORDING
            return [GestureEmit("record_start")]
        return []


class GestureRecognizer(QObject):
    """Qt wrapper that turns input events into shot/record signals."""

    shot_requested = Signal()
    record_started = Signal()
    record_stopped = Signal()

    def __init__(
        self,
        binding: TriggerBinding,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._binding = binding
        self._machine = GestureStateMachine(binding.hold_threshold_ms)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(binding.hold_threshold_ms)
        self._hold_timer.timeout.connect(self._on_hold_timeout)

    @property
    def state(self) -> GestureState:
        return self._machine.state

    def set_binding(self, binding: TriggerBinding) -> None:
        self._binding = binding
        self._machine = GestureStateMachine(binding.hold_threshold_ms)
        self._hold_timer.setInterval(binding.hold_threshold_ms)
        self._hold_timer.stop()

    def handle_event(self, event: InputEvent) -> None:
        """Subscribe target for :class:`~rin.input.base.ListenerBase`."""

        if not binding_matches_event(self._binding, event):
            return
        now = event.timestamp_ms or InputEvent.now_ms()
        emits: list[GestureEmit] = []
        if event.kind == "press":
            emits = self._machine.on_press(now)
            self._hold_timer.start()
        elif event.kind == "release":
            emits = self._machine.on_release(now)
            self._hold_timer.stop()
        self._dispatch(emits)

    def _on_hold_timeout(self) -> None:
        emits = self._machine.tick(InputEvent.now_ms())
        self._dispatch(emits)

    def _dispatch(self, emits: list[GestureEmit]) -> None:
        for e in emits:
            if e.kind == "shot":
                log.debug("Gesture: shot_requested")
                self.shot_requested.emit()
            elif e.kind == "record_start":
                log.debug("Gesture: record_started")
                self.record_started.emit()
            elif e.kind == "record_stop":
                log.debug("Gesture: record_stopped")
                self.record_stopped.emit()

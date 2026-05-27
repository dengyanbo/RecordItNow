"""Gesture state machine tests — pure Python, no Qt event loop."""
from __future__ import annotations

from rin.input.gesture import GestureState, GestureStateMachine


def test_tap_emits_shot() -> None:
    sm = GestureStateMachine(hold_threshold_ms=500)
    assert sm.on_press(0.0) == []
    out = sm.on_release(100.0)
    assert [e.kind for e in out] == ["shot"]
    assert sm.state is GestureState.IDLE


def test_hold_emits_record_start_then_stop() -> None:
    sm = GestureStateMachine(hold_threshold_ms=500)
    sm.on_press(0.0)
    start = sm.tick(500.0)
    assert [e.kind for e in start] == ["record_start"]
    assert sm.state is GestureState.RECORDING
    stop = sm.on_release(800.0)
    assert [e.kind for e in stop] == ["record_stop"]
    assert sm.state is GestureState.IDLE


def test_tick_before_threshold_is_noop() -> None:
    sm = GestureStateMachine(hold_threshold_ms=500)
    sm.on_press(0.0)
    assert sm.tick(100.0) == []
    assert sm.state is GestureState.PRESSED


def test_repeated_presses_ignored_in_pressed_state() -> None:
    sm = GestureStateMachine(hold_threshold_ms=500)
    sm.on_press(0.0)
    sm.on_press(50.0)  # auto-repeat — should be ignored
    out = sm.on_release(100.0)
    assert [e.kind for e in out] == ["shot"]


def test_release_without_press_is_noop() -> None:
    sm = GestureStateMachine()
    assert sm.on_release(123.0) == []


def test_long_press_with_late_release_still_emits_record_pair() -> None:
    # If the QTimer never fires (heavy load) but the release is past threshold,
    # the state machine still emits a record_start/record_stop pair to be safe.
    sm = GestureStateMachine(hold_threshold_ms=500)
    sm.on_press(0.0)
    out = sm.on_release(700.0)
    assert [e.kind for e in out] == ["record_start", "record_stop"]


def test_reset_returns_to_idle() -> None:
    sm = GestureStateMachine()
    sm.on_press(0.0)
    sm.reset()
    assert sm.state is GestureState.IDLE

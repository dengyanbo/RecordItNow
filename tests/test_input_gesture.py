"""Gesture state machine tests — pure Python, no Qt event loop."""
from __future__ import annotations

from rin.config import TriggerBinding
from rin.input.base import InputEvent
from rin.input.gesture import GestureRecognizer, GestureState, GestureStateMachine


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


def test_recognizer_keyboard_autorepeat_arms_hold_timer_once(qapp, monkeypatch) -> None:
    """Regression: keyboard auto-repeat must not keep restarting the hold timer.

    Holding a key emits repeated ``press`` events (OS auto-repeat). The old
    wrapper called ``QTimer.start()`` on every press, so the 500 ms single-shot
    timer was reset every few tens of ms and never fired — a hold only started
    recording on release via the fallback. The timer must be armed exactly once
    on the IDLE -> PRESSED transition and left running through the repeats.
    """

    binding = TriggerBinding(source="keyboard", key="f12", hold_threshold_ms=500)
    rec = GestureRecognizer(binding)

    starts = 0
    real_start = rec._hold_timer.start

    def counting_start(*args, **kwargs):
        nonlocal starts
        starts += 1
        return real_start(*args, **kwargs)

    monkeypatch.setattr(rec._hold_timer, "start", counting_start)

    def press(ts: float) -> None:
        rec.handle_event(
            InputEvent(kind="press", source="keyboard", identifier="f12", timestamp_ms=ts)
        )

    press(1000.0)  # genuine first press
    for i in range(6):  # OS auto-repeat while the key is held
        press(1000.0 + i)

    assert starts == 1, "hold timer must be armed once, not restarted by auto-repeat"
    assert rec.state is GestureState.PRESSED

    # Once the threshold elapses the hold path must start recording while held.
    monkeypatch.setattr(InputEvent, "now_ms", staticmethod(lambda: 1600.0))
    recorded: list[str] = []
    rec.record_started.connect(lambda: recorded.append("start"))
    rec._on_hold_timeout()
    assert recorded == ["start"]
    assert rec.state is GestureState.RECORDING

"""Manager wiring tests: queue listener events → recognizer; learn-mode interception."""
from __future__ import annotations

from PySide6.QtTest import QSignalSpy

from rin.config import RinConfig, TriggerBinding
from rin.input.base import InputEvent
from rin.input.manager import InputManager


def _drain(qapp) -> None:
    """Run pending queued events until the event queue is empty."""

    for _ in range(20):
        qapp.processEvents()


def test_tap_emits_shot_requested(qapp) -> None:
    cfg = RinConfig(trigger=TriggerBinding(source="keyboard", key="f12"))
    mgr = InputManager(cfg)
    spy = QSignalSpy(mgr.shot_requested)
    mgr._post_event(
        InputEvent(kind="press", source="keyboard", identifier="f12", timestamp_ms=0.0)
    )
    _drain(qapp)
    mgr._post_event(
        InputEvent(kind="release", source="keyboard", identifier="f12", timestamp_ms=100.0)
    )
    _drain(qapp)
    assert spy.count() == 1


def test_paused_manager_drops_events(qapp) -> None:
    cfg = RinConfig(trigger=TriggerBinding(source="keyboard", key="f12"))
    mgr = InputManager(cfg)
    mgr.set_paused(True)
    spy = QSignalSpy(mgr.shot_requested)
    mgr._post_event(InputEvent(kind="press", source="keyboard", identifier="f12"))
    mgr._post_event(
        InputEvent(kind="release", source="keyboard", identifier="f12", timestamp_ms=100.0)
    )
    _drain(qapp)
    assert spy.count() == 0


def test_learn_mode_intercepts_and_updates_binding(qapp) -> None:
    cfg = RinConfig(trigger=TriggerBinding(source="keyboard", key="f12"))
    mgr = InputManager(cfg)
    captured: list = []
    mgr.start_learn(on_captured=captured.append)
    mgr._post_event(
        InputEvent(kind="press", source="keyboard", identifier="f7", timestamp_ms=10.0)
    )
    _drain(qapp)
    assert len(captured) == 1
    assert captured[0].key == "f7"
    assert cfg.trigger.key == "f7"


def test_non_matching_event_ignored(qapp) -> None:
    cfg = RinConfig(trigger=TriggerBinding(source="keyboard", key="f12"))
    mgr = InputManager(cfg)
    spy = QSignalSpy(mgr.shot_requested)
    mgr._post_event(InputEvent(kind="press", source="keyboard", identifier="a"))
    mgr._post_event(InputEvent(kind="release", source="keyboard", identifier="a"))
    _drain(qapp)
    assert spy.count() == 0

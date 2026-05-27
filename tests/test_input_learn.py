"""Learn-mode tests."""
from __future__ import annotations

from rin.input.base import InputEvent
from rin.input.learn_mode import LearnRecorder


def test_first_press_is_captured() -> None:
    rec = LearnRecorder(hold_threshold_ms=750)
    rec.handle_event(
        InputEvent(kind="press", source="keyboard", identifier="f9", timestamp_ms=10.0)
    )
    binding = rec.captured
    assert binding is not None
    assert binding.source == "keyboard"
    assert binding.key == "f9"
    assert binding.hold_threshold_ms == 750
    assert binding.label == "Key: f9"


def test_release_events_are_ignored() -> None:
    rec = LearnRecorder()
    rec.handle_event(
        InputEvent(kind="release", source="keyboard", identifier="f9")
    )
    assert rec.captured is None


def test_subsequent_events_ignored_after_capture() -> None:
    rec = LearnRecorder()
    rec.handle_event(InputEvent(kind="press", source="keyboard", identifier="f9"))
    first = rec.captured
    rec.handle_event(InputEvent(kind="press", source="keyboard", identifier="f10"))
    assert rec.captured is first


def test_callback_invoked_with_binding() -> None:
    seen: list = []
    rec = LearnRecorder(on_captured=seen.append)
    rec.handle_event(
        InputEvent(
            kind="press",
            source="hid",
            identifier="1234:5678",
            vendor_id=0x1234,
            product_id=0x5678,
            usage_page=12,
            usage=224,
        )
    )
    assert len(seen) == 1
    assert seen[0].source == "hid"
    assert seen[0].vendor_id == 0x1234
    assert seen[0].label.startswith("HID")


def test_wait_returns_captured_or_none() -> None:
    rec = LearnRecorder()
    # No event yet: wait returns None on short timeout.
    assert rec.wait(timeout_seconds=0.01) is None
    rec.handle_event(InputEvent(kind="press", source="mouse", identifier="x1"))
    assert rec.wait(timeout_seconds=0.5) is not None

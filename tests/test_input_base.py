"""Tests for shared event types and binding matching."""
from __future__ import annotations

from rin.config import TriggerBinding
from rin.input.base import InputEvent, binding_matches_event


def _make_event(**overrides) -> InputEvent:
    defaults = dict(kind="press", source="keyboard", identifier="f12", timestamp_ms=0.0)
    defaults.update(overrides)
    return InputEvent(**defaults)


def test_event_now_ms_monotonic() -> None:
    a = InputEvent.now_ms()
    b = InputEvent.now_ms()
    assert b >= a


def test_binding_matches_keyboard_case_insensitive() -> None:
    binding = TriggerBinding(source="keyboard", key="F12")
    assert binding_matches_event(binding, _make_event(identifier="f12"))
    assert not binding_matches_event(binding, _make_event(identifier="f11"))


def test_binding_does_not_match_different_source() -> None:
    binding = TriggerBinding(source="keyboard", key="f12")
    event = _make_event(source="mouse", identifier="f12")
    assert not binding_matches_event(binding, event)


def test_unset_binding_matches_nothing() -> None:
    assert not binding_matches_event(TriggerBinding(), _make_event())


def test_binding_matches_hid_by_vid_pid() -> None:
    binding = TriggerBinding(source="hid", vendor_id=0x1234, product_id=0x5678)
    ev = _make_event(
        source="hid",
        identifier="1234:5678",
        vendor_id=0x1234,
        product_id=0x5678,
        usage_page=12,
        usage=224,
    )
    assert binding_matches_event(binding, ev)
    # Different vendor → no match.
    assert not binding_matches_event(
        binding, _make_event(source="hid", identifier="9999:5678", vendor_id=0x9999, product_id=0x5678)
    )


def test_binding_matches_hid_optional_usage() -> None:
    binding = TriggerBinding(
        source="hid",
        vendor_id=0x1234,
        product_id=0x5678,
        usage_page=12,
        usage=224,
    )
    ev = _make_event(
        source="hid",
        identifier="1234:5678",
        vendor_id=0x1234,
        product_id=0x5678,
        usage_page=12,
        usage=224,
    )
    assert binding_matches_event(binding, ev)
    # Mismatched usage → no match.
    assert not binding_matches_event(
        binding,
        _make_event(
            source="hid",
            identifier="1234:5678",
            vendor_id=0x1234,
            product_id=0x5678,
            usage_page=12,
            usage=99,
        ),
    )

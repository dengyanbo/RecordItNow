"""Tests for the reserved-key warning helper."""
from __future__ import annotations

from rin.config import TriggerBinding
from rin.input.reserved_keys import RESERVED_KEYS, lookup_reserved


def test_reserved_keyboard_keys_flagged_with_correct_severity() -> None:
    """alt+tab is an error (would break the OS); f12 is a warning (browser
    devtools); CTRL+C and `` ctrl+c `` exercise uppercase + whitespace
    normalisation."""
    cases = [
        ("alt+tab", "error"),
        ("f12", "warning"),
        ("CTRL+C", "warning"),    # normalised to ctrl+c
        (" ctrl+c ", "warning"),  # whitespace stripped
    ]
    for key, expected_severity in cases:
        warn = lookup_reserved(TriggerBinding(source="keyboard", key=key))
        assert warn is not None, f"expected {key!r} to be reserved"
        _, severity = warn
        assert severity == expected_severity, f"{key!r}: got {severity}"


def test_unflagged_bindings_return_none() -> None:
    """Unset / no-key / safe keys / mouse / HID bindings are never flagged."""
    bindings = [
        TriggerBinding(source="unset"),
        TriggerBinding(source="keyboard", key=None),
        TriggerBinding(source="keyboard", key="f9"),
        TriggerBinding(source="mouse", key="x1"),
        TriggerBinding(
            source="hid", vendor_id=0x1234, product_id=0x5678,
            usage_page=12, usage=224,
        ),
    ]
    for b in bindings:
        assert lookup_reserved(b) is None, f"unexpected flag for {b}"


def test_reserved_keys_table_is_well_formed() -> None:
    """Defensive: every entry must be (str, "error"|"warning") and keys
    must already be lower-case (we use them as a dict lookup with a
    lower-cased query)."""
    for key, payload in RESERVED_KEYS.items():
        assert key == key.lower(), f"{key!r} is not lower-case"
        reason, severity = payload
        assert isinstance(reason, str) and reason.strip()
        assert severity in {"error", "warning"}


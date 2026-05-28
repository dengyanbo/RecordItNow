"""Tests for the reserved-key warning helper."""
from __future__ import annotations

from rin.config import TriggerBinding
from rin.input.reserved_keys import RESERVED_KEYS, lookup_reserved


def test_error_severity_for_alt_tab() -> None:
    b = TriggerBinding(source="keyboard", key="alt+tab")
    warn = lookup_reserved(b)
    assert warn is not None
    reason, severity = warn
    assert severity == "error"
    assert "switch" in reason.lower()


def test_warning_severity_for_f12() -> None:
    b = TriggerBinding(source="keyboard", key="f12")
    warn = lookup_reserved(b)
    assert warn is not None
    _, severity = warn
    assert severity == "warning"


def test_uppercase_key_normalised() -> None:
    b = TriggerBinding(source="keyboard", key="CTRL+C")
    assert lookup_reserved(b) is not None


def test_extra_whitespace_normalised() -> None:
    b = TriggerBinding(source="keyboard", key=" ctrl+c ")
    assert lookup_reserved(b) is not None


def test_unbound_returns_none() -> None:
    b = TriggerBinding(source="unset")
    assert lookup_reserved(b) is None


def test_no_key_returns_none() -> None:
    b = TriggerBinding(source="keyboard", key=None)
    assert lookup_reserved(b) is None


def test_safe_key_not_flagged() -> None:
    b = TriggerBinding(source="keyboard", key="f9")
    assert lookup_reserved(b) is None


def test_mouse_binding_never_flagged() -> None:
    # Even if a wild "x1" entry existed, mouse buttons are out of scope.
    b = TriggerBinding(source="mouse", key="x1")
    assert lookup_reserved(b) is None


def test_hid_binding_never_flagged() -> None:
    b = TriggerBinding(
        source="hid",
        vendor_id=0x1234,
        product_id=0x5678,
        usage_page=12,
        usage=224,
    )
    assert lookup_reserved(b) is None


def test_reserved_keys_table_is_well_formed() -> None:
    # Defensive: every entry must be (str, "error"|"warning") and keys
    # must already be lower-case (we use them as a dict lookup with a
    # lower-cased query).
    for key, payload in RESERVED_KEYS.items():
        assert key == key.lower(), f"{key!r} is not lower-case"
        reason, severity = payload
        assert isinstance(reason, str) and reason.strip()
        assert severity in {"error", "warning"}

"""Idle detector smoke tests (Windows-only logic, mocked on Windows too)."""
from __future__ import annotations

import sys

from rin.analysis.idle_detector import get_idle_seconds, is_idle


def test_get_idle_seconds_returns_float() -> None:
    val = get_idle_seconds()
    assert isinstance(val, float)
    assert val >= 0.0


def test_non_windows_returns_zero(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert get_idle_seconds() == 0.0
    assert is_idle(threshold_seconds=1.0) is False

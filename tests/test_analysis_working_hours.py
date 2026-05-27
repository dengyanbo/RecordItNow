"""Working-hours predicate tests."""
from __future__ import annotations

from datetime import datetime

from rin.analysis.working_hours import is_within_working_hours
from rin.config import WorkingHours


def test_disabled_schedule_returns_false() -> None:
    wh = WorkingHours(enabled=False)
    assert is_within_working_hours(wh, now=datetime(2026, 5, 21, 12, 0)) is False


def test_within_window_on_working_day() -> None:
    wh = WorkingHours(weekdays=[0, 1, 2, 3, 4], start_hour=9, end_hour=18)
    # Thursday 14:00
    assert is_within_working_hours(wh, now=datetime(2026, 5, 21, 14, 0)) is True


def test_before_window_returns_false() -> None:
    wh = WorkingHours(weekdays=[0, 1, 2, 3, 4], start_hour=9, end_hour=18)
    assert is_within_working_hours(wh, now=datetime(2026, 5, 21, 7, 30)) is False


def test_weekend_returns_false() -> None:
    wh = WorkingHours(weekdays=[0, 1, 2, 3, 4], start_hour=9, end_hour=18)
    # Saturday
    assert is_within_working_hours(wh, now=datetime(2026, 5, 23, 14, 0)) is False


def test_overnight_window() -> None:
    wh = WorkingHours(weekdays=[0, 1, 2, 3, 4, 5, 6], start_hour=22, end_hour=6)
    assert is_within_working_hours(wh, now=datetime(2026, 5, 21, 23, 0)) is True
    assert is_within_working_hours(wh, now=datetime(2026, 5, 21, 4, 0)) is True
    assert is_within_working_hours(wh, now=datetime(2026, 5, 21, 12, 0)) is False

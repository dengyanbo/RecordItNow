"""Working-hours evaluation. Pure logic, easy to unit-test."""
from __future__ import annotations

from datetime import datetime, time

from ..config import WorkingHours


def is_within_working_hours(schedule: WorkingHours, *, now: datetime | None = None) -> bool:
    """Return True if ``now`` is within ``schedule``'s configured working window.

    The schedule is opt-in: when ``schedule.enabled`` is False, this
    function always returns False (i.e. all hours are "off-hours" — fine
    to run analysis whenever).
    """

    if not schedule.enabled:
        return False
    now = now or datetime.now()
    if now.weekday() not in schedule.weekdays:
        return False
    start = time(hour=schedule.start_hour)
    end = time(hour=schedule.end_hour)
    current = now.time()
    if start <= end:
        return start <= current < end
    # Overnight window (e.g. 22 → 6): match either side of midnight.
    return current >= start or current < end

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from rin.reports.integrations.base import CalendarEvent, CalendarProvider


def test_calendar_event_is_frozen() -> None:
    event = CalendarEvent(
        start=datetime(2024, 1, 1, 13, 0),
        end=datetime(2024, 1, 1, 14, 0),
        subject="Engineering Sync",
    )

    with pytest.raises(FrozenInstanceError):
        event.subject = "Focus time"  # type: ignore[misc]



def test_calendar_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        CalendarProvider()  # type: ignore[abstract]

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    start: datetime
    end: datetime
    subject: str
    organizer: str | None = None
    location: str | None = None


class CalendarProvider(ABC):
    @abstractmethod
    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

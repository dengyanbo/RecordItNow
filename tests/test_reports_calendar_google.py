from __future__ import annotations

import json
import sys
import types
from datetime import datetime

from rin.reports.integrations.base import CalendarEvent
from rin.reports.integrations.google import GoogleCalendarProvider


class _FakeCredentials:
    valid = True
    refresh_token = "refresh-token"

    @classmethod
    def from_authorized_user_info(cls, info: dict, *, scopes: list[str]):
        cls.last_info = info
        cls.last_scopes = scopes
        return cls()

    def to_json(self) -> str:
        return json.dumps({"token": "saved-token"})


class _FakeEventsResource:
    def __init__(self, seen: dict[str, object]) -> None:
        self._seen = seen

    def list(self, **kwargs):
        self._seen["list_kwargs"] = kwargs
        return self

    def execute(self) -> dict:
        return {
            "items": [
                {
                    "summary": "Engineering Sync",
                    "start": {"dateTime": "2024-01-01T13:00:00"},
                    "end": {"dateTime": "2024-01-01T14:00:00"},
                    "organizer": {"displayName": "Taylor"},
                    "location": "Board Room",
                }
            ]
        }


class _FakeCalendarService:
    def __init__(self, seen: dict[str, object]) -> None:
        self._seen = seen

    def events(self) -> _FakeEventsResource:
        return _FakeEventsResource(self._seen)



def test_google_fetch_events_parses_calendar_response(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_build(service_name: str, version: str, *, credentials, cache_discovery: bool):
        seen["build_args"] = (service_name, version, credentials, cache_discovery)
        return _FakeCalendarService(seen)

    fake_keyring = types.ModuleType("keyring")
    fake_keyring.get_password = lambda service, username: json.dumps({"token": "cached-token"})
    fake_keyring.set_password = lambda service, username, value: seen.setdefault("saved", value)

    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google_oauth2 = types.ModuleType("google.oauth2")
    fake_google_oauth2.__path__ = []
    fake_google_credentials = types.ModuleType("google.oauth2.credentials")
    fake_google_credentials.Credentials = _FakeCredentials

    fake_googleapiclient = types.ModuleType("googleapiclient")
    fake_googleapiclient.__path__ = []
    fake_google_discovery = types.ModuleType("googleapiclient.discovery")
    fake_google_discovery.build = fake_build

    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_google_oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", fake_google_credentials)
    monkeypatch.setitem(sys.modules, "googleapiclient", fake_googleapiclient)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", fake_google_discovery)

    provider = GoogleCalendarProvider()
    events = provider.fetch_events(datetime(2024, 1, 1, 9, 0), datetime(2024, 1, 1, 17, 0))

    assert _FakeCredentials.last_info == {"token": "cached-token"}
    assert _FakeCredentials.last_scopes == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert seen["list_kwargs"] == {
        "calendarId": "primary",
        "timeMin": "2024-01-01T09:00:00",
        "timeMax": "2024-01-01T17:00:00",
        "singleEvents": True,
        "orderBy": "startTime",
    }
    assert seen["build_args"][0:2] == ("calendar", "v3")
    assert seen["build_args"][3] is False
    assert events == [
        CalendarEvent(
            start=datetime(2024, 1, 1, 13, 0),
            end=datetime(2024, 1, 1, 14, 0),
            subject="Engineering Sync",
            organizer="Taylor",
            location="Board Room",
        )
    ]

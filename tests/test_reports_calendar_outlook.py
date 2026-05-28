from __future__ import annotations

import types
from datetime import datetime

from rin.reports.integrations.base import CalendarEvent
from rin.reports.integrations.outlook import OutlookCalendarProvider


class _FakeTokenCache:
    def __init__(self) -> None:
        self.has_state_changed = False
        self.deserialized: str | None = None

    def deserialize(self, payload: str) -> None:
        self.deserialized = payload

    def serialize(self) -> str:
        return "serialized-cache"


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "value": [
                {
                    "subject": "Engineering Sync",
                    "start": {"dateTime": "2024-01-01T13:00:00"},
                    "end": {"dateTime": "2024-01-01T14:00:00"},
                    "organizer": {"emailAddress": {"name": "Alex"}},
                    "location": {"displayName": "Teams"},
                }
            ]
        }



def test_outlook_fetch_events_parses_graph_response(monkeypatch) -> None:
    seen: dict[str, object] = {}
    token_cache = _FakeTokenCache()

    class _FakePublicClientApplication:
        def __init__(self, client_id: str, *, authority: str, token_cache: _FakeTokenCache) -> None:
            seen["client_id"] = client_id
            seen["authority"] = authority
            seen["token_cache"] = token_cache

        def get_accounts(self) -> list[dict[str, str]]:
            return [{"username": "alex@example.com"}]

        def acquire_token_silent(self, scopes: list[str], *, account: dict[str, str]) -> dict[str, str]:
            seen["scopes"] = scopes
            seen["account"] = account
            return {"access_token": "graph-token"}

    def fake_get(url: str, *, headers: dict[str, str], params: dict[str, str], timeout: int):
        seen["url"] = url
        seen["headers"] = headers
        seen["params"] = params
        seen["timeout"] = timeout
        return _FakeResponse()

    fake_msal = types.ModuleType("msal")
    fake_msal.SerializableTokenCache = lambda: token_cache
    fake_msal.PublicClientApplication = _FakePublicClientApplication

    fake_requests = types.ModuleType("requests")
    fake_requests.get = fake_get

    fake_keyring = types.ModuleType("keyring")
    fake_keyring.get_password = lambda service, username: "cached-token-cache"
    fake_keyring.set_password = lambda service, username, value: seen.setdefault("saved", value)

    monkeypatch.setitem(__import__("sys").modules, "msal", fake_msal)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)

    provider = OutlookCalendarProvider(client_id="client-id", tenant_id="contoso", timeout_seconds=12)
    events = provider.fetch_events(datetime(2024, 1, 1, 9, 0), datetime(2024, 1, 1, 17, 0))

    assert token_cache.deserialized == "cached-token-cache"
    assert seen["client_id"] == "client-id"
    assert seen["authority"] == "https://login.microsoftonline.com/contoso"
    assert seen["headers"] == {
        "Authorization": "Bearer graph-token",
        "Accept": "application/json",
    }
    assert seen["params"] == {
        "startDateTime": "2024-01-01T09:00:00",
        "endDateTime": "2024-01-01T17:00:00",
        "$select": "subject,organizer,location,start,end",
        "$orderby": "start/dateTime",
    }
    assert seen["timeout"] == 12
    assert events == [
        CalendarEvent(
            start=datetime(2024, 1, 1, 13, 0),
            end=datetime(2024, 1, 1, 14, 0),
            subject="Engineering Sync",
            organizer="Alex",
            location="Teams",
        )
    ]

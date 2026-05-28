from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from .base import CalendarEvent, CalendarProvider

_GRAPH_URL = "https://graph.microsoft.com/v1.0/me/calendarview"
_KEYRING_SERVICE = "rin-outlook-calendar"
_KEYRING_USERNAME = "token-cache"


class OutlookCalendarProvider(CalendarProvider):
    SCOPES = ["openid", "offline_access", "User.Read", "Calendars.Read"]

    def __init__(
        self,
        *,
        client_id: str | None = None,
        tenant_id: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.client_id = client_id or os.environ.get("RIN_OUTLOOK_CALENDAR_CLIENT_ID")
        self.tenant_id = tenant_id or os.environ.get("RIN_OUTLOOK_CALENDAR_TENANT_ID", "common")
        self.timeout_seconds = timeout_seconds

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    def authenticate(self) -> None:
        self._get_access_token(interactive=True)

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        import requests

        token = self._get_access_token(interactive=False)
        response = requests.get(
            _GRAPH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            params={
                "startDateTime": start.isoformat(),
                "endDateTime": end.isoformat(),
                "$select": "subject,organizer,location,start,end",
                "$orderby": "start/dateTime",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            self._parse_event(item)
            for item in payload.get("value", [])
            if item.get("start") and item.get("end")
        ]

    def _get_access_token(self, *, interactive: bool) -> str:
        cache = self._load_token_cache()
        app = self._make_client(cache)
        accounts = list(app.get_accounts())
        result: dict[str, Any] | None = None
        if accounts:
            result = app.acquire_token_silent(self.SCOPES, account=accounts[0])
        if result is None and interactive:
            result = app.acquire_token_interactive(scopes=self.SCOPES)
        self._persist_token_cache(cache)
        if result and "access_token" in result:
            return str(result["access_token"])
        error = self._error_message(result)
        if interactive:
            raise RuntimeError(error or "Outlook calendar sign-in failed")
        raise RuntimeError(error or "Outlook calendar is not signed in")

    def _load_token_cache(self):
        import keyring
        import msal

        cache = msal.SerializableTokenCache()
        serialized = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if serialized:
            cache.deserialize(serialized)
        return cache

    def _persist_token_cache(self, cache) -> None:
        if not getattr(cache, "has_state_changed", False):
            return
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, cache.serialize())

    def _make_client(self, token_cache):
        import msal

        if not self.client_id:
            raise RuntimeError(
                "Outlook calendar OAuth client id missing; set RIN_OUTLOOK_CALENDAR_CLIENT_ID."
            )
        return msal.PublicClientApplication(
            self.client_id,
            authority=self.authority,
            token_cache=token_cache,
        )

    @staticmethod
    def _parse_event(payload: dict[str, Any]) -> CalendarEvent:
        organizer_info = payload.get("organizer", {}).get("emailAddress", {})
        organizer = organizer_info.get("name") or organizer_info.get("address")
        location = payload.get("location", {}).get("displayName") or None
        return CalendarEvent(
            start=_parse_datetime(payload["start"]["dateTime"]),
            end=_parse_datetime(payload["end"]["dateTime"]),
            subject=payload.get("subject") or "(untitled event)",
            organizer=organizer,
            location=location,
        )

    @staticmethod
    def _error_message(result: dict[str, Any] | None) -> str | None:
        if not result:
            return None
        return (
            result.get("error_description")
            or result.get("error")
            or result.get("suberror")
        )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

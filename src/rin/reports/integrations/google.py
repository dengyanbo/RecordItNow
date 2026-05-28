from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .base import CalendarEvent, CalendarProvider

_KEYRING_SERVICE = "rin-google-calendar"
_KEYRING_USERNAME = "credentials"


class GoogleCalendarProvider(CalendarProvider):
    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

    def __init__(
        self,
        *,
        client_config: dict[str, Any] | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.client_config = client_config
        self.timeout_seconds = timeout_seconds

    def authenticate(self) -> None:
        flow = self._make_flow()
        creds = flow.run_local_server(port=0, open_browser=True)
        self._persist_credentials(creds)

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        from googleapiclient.discovery import build

        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Google calendar is not signed in")
        if not getattr(creds, "valid", False):
            refresh_token = getattr(creds, "refresh_token", None)
            if not refresh_token:
                raise RuntimeError("Google calendar sign-in expired; sign in again")
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            self._persist_credentials(creds)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        payload = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [
            self._parse_event(item)
            for item in payload.get("items", [])
            if item.get("start") and item.get("end")
        ]

    def _load_credentials(self):
        import keyring
        from google.oauth2.credentials import Credentials

        payload = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if not payload:
            return None
        return Credentials.from_authorized_user_info(json.loads(payload), scopes=self.SCOPES)

    def _persist_credentials(self, creds) -> None:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, creds.to_json())

    def _make_flow(self):
        from google_auth_oauthlib.flow import InstalledAppFlow

        return InstalledAppFlow.from_client_config(self._resolve_client_config(), self.SCOPES)

    def _resolve_client_config(self) -> dict[str, Any]:
        if self.client_config is not None:
            return self.client_config
        raw = os.environ.get("RIN_GOOGLE_CALENDAR_CLIENT_CONFIG_JSON")
        if raw:
            return json.loads(raw)
        client_id = os.environ.get("RIN_GOOGLE_CALENDAR_CLIENT_ID")
        client_secret = os.environ.get("RIN_GOOGLE_CALENDAR_CLIENT_SECRET")
        if client_id and client_secret:
            return {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        raise RuntimeError(
            "Google calendar OAuth client config missing; set "
            "RIN_GOOGLE_CALENDAR_CLIENT_CONFIG_JSON or "
            "RIN_GOOGLE_CALENDAR_CLIENT_ID/RIN_GOOGLE_CALENDAR_CLIENT_SECRET."
        )

    @staticmethod
    def _parse_event(payload: dict[str, Any]) -> CalendarEvent:
        organizer_info = payload.get("organizer", {})
        organizer = organizer_info.get("displayName") or organizer_info.get("email")
        start = payload.get("start", {})
        end = payload.get("end", {})
        start_value = start.get("dateTime") or start.get("date")
        end_value = end.get("dateTime") or end.get("date")
        return CalendarEvent(
            start=_parse_datetime(start_value),
            end=_parse_datetime(end_value),
            subject=payload.get("summary") or "(untitled event)",
            organizer=organizer,
            location=payload.get("location") or None,
        )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

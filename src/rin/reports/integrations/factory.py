from __future__ import annotations

import importlib

from ...config import RinConfig
from .base import CalendarProvider


def make_calendar_provider(cfg: RinConfig) -> CalendarProvider | None:
    name = cfg.reports.calendar_provider
    if name == "none":
        return None
    try:
        if name == "outlook":
            importlib.import_module("keyring")
            importlib.import_module("msal")
            importlib.import_module("requests")
            from .outlook import OutlookCalendarProvider

            return OutlookCalendarProvider()
        if name == "google":
            importlib.import_module("keyring")
            importlib.import_module("google.oauth2.credentials")
            importlib.import_module("google_auth_oauthlib.flow")
            importlib.import_module("googleapiclient.discovery")
            from .google import GoogleCalendarProvider

            return GoogleCalendarProvider()
    except ImportError:
        return None
    return None

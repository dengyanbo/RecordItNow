from __future__ import annotations

from unittest.mock import patch

from rin.config import RinConfig
from rin.reports.integrations.factory import make_calendar_provider
from rin.reports.integrations.google import GoogleCalendarProvider
from rin.reports.integrations.outlook import OutlookCalendarProvider


def test_make_calendar_provider_returns_none_for_none() -> None:
    cfg = RinConfig()
    cfg.reports.calendar_provider = "none"

    assert make_calendar_provider(cfg) is None



def test_make_calendar_provider_dispatches_outlook() -> None:
    cfg = RinConfig()
    cfg.reports.calendar_provider = "outlook"

    with patch("rin.reports.integrations.factory.importlib.import_module", return_value=object()):
        provider = make_calendar_provider(cfg)

    assert isinstance(provider, OutlookCalendarProvider)



def test_make_calendar_provider_dispatches_google() -> None:
    cfg = RinConfig()
    cfg.reports.calendar_provider = "google"

    with patch("rin.reports.integrations.factory.importlib.import_module", return_value=object()):
        provider = make_calendar_provider(cfg)

    assert isinstance(provider, GoogleCalendarProvider)



def test_make_calendar_provider_returns_none_when_package_missing() -> None:
    cfg = RinConfig()
    cfg.reports.calendar_provider = "google"

    def fake_import(name: str):
        if name == "googleapiclient.discovery":
            raise ImportError("missing")
        return object()

    with patch("rin.reports.integrations.factory.importlib.import_module", side_effect=fake_import):
        assert make_calendar_provider(cfg) is None

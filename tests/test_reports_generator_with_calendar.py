from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.reports.generator import CaptureItem, daily_period, generate_report
from rin.reports.integrations.base import CalendarEvent, CalendarProvider
from rin.storage import db, init_db


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


class _PromptCapturingProvider(Provider):
    name = "fake"
    model = "fake-1"

    def __init__(self) -> None:
        self.prompt = ""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="")

    def analyze_text(self, prompt, *, system=None):
        self.prompt = prompt
        return "# LLM Report\n\n## Highlights\n- calendar aware"

    def chat(self, messages):
        return ""


class _StaticCalendarProvider(CalendarProvider):
    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                start=datetime(2024, 1, 1, 13, 0),
                end=datetime(2024, 1, 1, 14, 0),
                subject="Engineering Sync",
                organizer="Alex",
                location="Teams",
            )
        ]


class _BoomCalendarProvider(CalendarProvider):
    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        raise RuntimeError("token expired")



def _sample_item() -> CaptureItem:
    return CaptureItem(
        id=1,
        kind="screenshot",
        started_at=datetime(2024, 1, 1, 12, 30),
        duration_ms=1000,
        monitor_count=1,
        summary="Worked on report generation.",
    )



def test_generate_report_injects_calendar_section(tmp_path: Path) -> None:
    cfg = RinConfig()
    cfg.reports.calendar_provider = "outlook"
    llm = _PromptCapturingProvider()
    period = daily_period(now=datetime(2024, 1, 2, 12, 0))

    with patch(
        "rin.reports.generator.make_calendar_provider",
        return_value=_StaticCalendarProvider(),
    ):
        result = generate_report(period, cfg, items=[_sample_item()], provider=llm, out_dir=tmp_path)

    assert result.path.exists()
    assert "## Calendar" in llm.prompt
    assert "Engineering Sync" in llm.prompt
    assert "organizer: Alex" in llm.prompt



def test_generate_report_continues_when_calendar_fetch_fails(tmp_path: Path) -> None:
    cfg = RinConfig()
    cfg.reports.calendar_provider = "google"
    llm = _PromptCapturingProvider()
    period = daily_period(now=datetime(2024, 1, 2, 12, 0))

    with patch(
        "rin.reports.generator.make_calendar_provider",
        return_value=_BoomCalendarProvider(),
    ), patch("rin.reports.generator.log.warning") as warning:
        result = generate_report(period, cfg, items=[_sample_item()], provider=llm, out_dir=tmp_path)

    assert result.path.exists()
    assert "## Calendar" not in llm.prompt
    assert result.body.startswith("# LLM Report")
    warning.assert_called_once()
    assert "Calendar fetch failed" in warning.call_args[0][0]

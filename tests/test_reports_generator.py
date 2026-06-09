"""Report generator tests."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.reports.generator import (
    CaptureItem,
    daily_period,
    generate_report,
    list_captures_for_period,
    weekly_period,
)
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Capture, Report


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


class _FakeProvider(Provider):
    name = "fake"
    model = "fake-1"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="")

    def analyze_text(self, prompt, *, system=None):
        return f"# LLM Report\n\nPrompt length: {len(prompt)}\n\n## Highlights\n- great day"

    def chat(self, messages):
        return ""


def _seed_captures(days_ago: int) -> int:
    # Anchor to noon of the target calendar day so the capture always lands
    # inside ``daily_period()`` (= yesterday 00:00 → today 00:00) regardless of
    # the wall-clock time when the test runs. Previously ``now - days - 2h``
    # could leak into the day-before-yesterday when run between 00:00 and 02:00.
    target_day = (datetime.now() - timedelta(days=days_ago)).date()
    start = datetime.combine(target_day, time(12, 0))
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="analyzed",
            started_at=start,
            ended_at=start + timedelta(seconds=1),
            duration_ms=1000,
        )
        s.add(cap)
        s.flush()
        s.add(
            Analysis(
                capture_id=cap.id,
                summary="A code editor with main.py",
                llm_provider="fake",
                llm_model="fake-1",
            )
        )
        return cap.id


def test_daily_period_is_previous_calendar_day() -> None:
    p = daily_period(now=datetime(2026, 5, 21, 14, 0))
    assert p.kind == "daily"
    assert p.start == datetime(2026, 5, 20)
    assert p.end == datetime(2026, 5, 21)


def test_weekly_period_is_previous_iso_week() -> None:
    # 2026-05-21 is a Thursday; previous ISO week is Mon 2026-05-11 → Mon 2026-05-18.
    p = weekly_period(now=datetime(2026, 5, 21, 14, 0))
    assert p.kind == "weekly"
    assert p.start == datetime(2026, 5, 11)
    assert p.end == datetime(2026, 5, 18)


def test_list_captures_in_period() -> None:
    cap_id = _seed_captures(days_ago=1)
    p = daily_period()
    items = list_captures_for_period(p)
    ids = [it.id for it in items]
    assert cap_id in ids
    item = next(it for it in items if it.id == cap_id)
    assert item.summary == "A code editor with main.py"


def test_generate_report_uses_provider_when_available(tmp_path: Path) -> None:
    _seed_captures(days_ago=1)
    p = daily_period()
    cfg = RinConfig()
    result = generate_report(p, cfg, provider=_FakeProvider(), out_dir=tmp_path)
    assert "LLM Report" in result.body
    assert result.path.exists()
    assert "## Highlights" in result.body
    with session() as s:
        rows = s.scalars(select(Report)).all()
    assert len(rows) == 1
    assert rows[0].kind == "daily"


def test_generate_report_offline_fallback(tmp_path: Path) -> None:
    cap_id = _seed_captures(days_ago=1)
    p = daily_period()
    cfg = RinConfig()
    cfg.llm.name = "none"  # force the offline path; otherwise the auto-created provider runs
    result = generate_report(p, cfg, out_dir=tmp_path)
    assert "RIN Report" in result.body
    assert f"cap-{cap_id}" in result.body
    assert "Generated offline" in result.body


def test_generate_report_with_no_captures_does_not_crash(tmp_path: Path) -> None:
    p = daily_period(now=datetime(2020, 1, 1, 12, 0))
    cfg = RinConfig()
    result = generate_report(p, cfg, provider=_FakeProvider(), out_dir=tmp_path)
    assert "No captures" in result.body or "0" in result.body
    assert result.path.exists()


def test_generate_report_is_idempotent_per_period(tmp_path: Path) -> None:
    _seed_captures(days_ago=1)
    p = daily_period()
    cfg = RinConfig()
    r1 = generate_report(p, cfg, provider=None, out_dir=tmp_path)
    r2 = generate_report(p, cfg, provider=None, out_dir=tmp_path)
    # Same period → same DB row id.
    assert r1.report_id == r2.report_id
    with session() as s:
        assert len(s.scalars(select(Report)).all()) == 1


def test_list_for_period_respects_window() -> None:
    _seed_captures(days_ago=30)  # outside the daily period
    p = daily_period()
    assert list_captures_for_period(p) == []


def test_capture_item_dataclass_carries_monitor_count() -> None:
    item = CaptureItem(
        id=1,
        kind="screenshot",
        started_at=datetime.now(),
        duration_ms=10,
        monitor_count=2,
    )
    assert item.monitor_count == 2

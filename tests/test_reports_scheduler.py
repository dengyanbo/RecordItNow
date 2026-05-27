"""Reports scheduler smoke tests."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rin.config import RinConfig
from rin.reports import ReportsScheduler
from rin.reports.generator import GeneratedReport, ReportPeriod


def _fake_runner_factory(captured: list):
    def _runner(cfg: RinConfig, period: ReportPeriod) -> GeneratedReport:
        captured.append(period)
        return GeneratedReport(
            report_id=1, path=Path("fake.md"), body="x", period=period
        )

    return _runner


def test_trigger_now_runs_daily_period_for_daily_cadence() -> None:
    cfg = RinConfig()
    cfg.reports.frequency = "daily"
    captured: list = []
    sched = ReportsScheduler(cfg, runner=_fake_runner_factory(captured))
    sched.trigger_now(now=datetime(2026, 5, 21, 14, 0))
    assert len(captured) == 1
    assert captured[0].kind == "daily"


def test_trigger_now_runs_weekly_for_weekly_cadence() -> None:
    cfg = RinConfig()
    cfg.reports.frequency = "weekly"
    captured: list = []
    sched = ReportsScheduler(cfg, runner=_fake_runner_factory(captured))
    sched.trigger_now(now=datetime(2026, 5, 21, 14, 0))
    assert len(captured) == 1
    assert captured[0].kind == "weekly"


def test_trigger_now_off_does_nothing() -> None:
    cfg = RinConfig()
    cfg.reports.frequency = "off"
    captured: list = []
    sched = ReportsScheduler(cfg, runner=_fake_runner_factory(captured))
    result = sched.trigger_now()
    assert result is None
    assert captured == []

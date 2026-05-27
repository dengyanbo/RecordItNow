"""Scheduled report generation.

A thin APScheduler wrapper. Cadence comes from
:class:`~rin.config.ReportsConfig`:

* ``daily``  — every day at 06:00, covering the previous calendar day.
* ``weekly`` — every Monday at 06:00, covering the previous ISO week.
* ``off``    — disabled.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..config import RinConfig
from ..utils.logging import get_logger
from .generator import (
    GeneratedReport,
    ReportPeriod,
    daily_period,
    generate_report,
    weekly_period,
)

log = get_logger(__name__)


def _default_runner(cfg: RinConfig, period: ReportPeriod) -> GeneratedReport:
    return generate_report(period, cfg)


class ReportsScheduler:
    def __init__(
        self,
        config: RinConfig,
        *,
        runner: Callable[[RinConfig, ReportPeriod], GeneratedReport] = _default_runner,
    ) -> None:
        self.config = config
        self.runner = runner
        self._scheduler: Any = None

    def start(self) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            log.warning("APScheduler not installed; reports scheduler disabled")
            return
        freq = self.config.reports.frequency
        if freq == "off":
            log.info("Reports cadence is 'off'; scheduler not started")
            return
        scheduler = BackgroundScheduler()
        if freq == "daily":
            trigger = CronTrigger(hour=6, minute=0)
        else:
            trigger = CronTrigger(day_of_week="mon", hour=6, minute=0)
        scheduler.add_job(self._tick, trigger, id="report_job", replace_existing=True)
        scheduler.start()
        self._scheduler = scheduler
        log.info(f"ReportsScheduler started (cadence={freq})")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            log.info("ReportsScheduler stopped")

    def trigger_now(self, *, now: datetime | None = None) -> GeneratedReport | None:
        if self.config.reports.frequency == "off":
            log.info("trigger_now: reports disabled, skipping")
            return None
        period = (
            daily_period(now)
            if self.config.reports.frequency == "daily"
            else weekly_period(now)
        )
        return self.runner(self.config, period)

    def _tick(self) -> None:
        try:
            self.trigger_now()
        except Exception as exc:
            log.error(f"Scheduled report run failed: {exc}")

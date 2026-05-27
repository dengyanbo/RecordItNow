"""Hourly analysis scheduler built on APScheduler.

Each tick we check the gate (``should_analyze_now``) and, if open,
spawn :func:`analyze_pending` in a background job.

The scheduler runs in its own thread inside the host Qt process; jobs
hit only SQLAlchemy + Chroma, not Qt widgets, so no UI thread bouncing
is needed.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from ..config import RinConfig
from ..utils.logging import get_logger
from .idle_detector import is_idle
from .summarizer import analyze_pending
from .working_hours import is_within_working_hours

log = get_logger(__name__)


def should_analyze_now(cfg: RinConfig, *, now: datetime | None = None) -> bool:
    """Gate: True when it's OK to spend CPU on the analysis pipeline."""

    if not cfg.analysis.hourly_enabled:
        return False
    if not cfg.analysis.require_idle_or_offhours:
        return True
    now = now or datetime.now()
    off_hours = not is_within_working_hours(cfg.working_hours, now=now)
    idle = is_idle(cfg.working_hours.idle_threshold_minutes * 60)
    return off_hours or idle


class AnalysisScheduler:
    """Wraps APScheduler so callers don't import it directly."""

    def __init__(
        self,
        config: RinConfig,
        *,
        job_fn: Callable[..., object] = analyze_pending,
        interval_minutes: int = 60,
    ) -> None:
        self.config = config
        self.job_fn = job_fn
        self.interval_minutes = interval_minutes
        self._scheduler = None
        self._progress_cb: Callable[[int, int, int], None] | None = None
        self._finished_cb: Callable[[int, int], None] | None = None
        # Guards _tick against concurrent invocations from the scheduled
        # APScheduler thread + manual "Analyze now" QThreadPool calls.
        # Non-blocking acquire — overlapping ticks just skip (R5 from review).
        self._tick_lock = threading.Lock()

    def set_progress_callback(
        self,
        progress_cb: Callable[[int, int, int], None] | None,
        *,
        finished_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        """Subscribe to per-capture progress and batch-finish events.

        ``progress_cb(index, total, capture_id)`` fires after each analyzed
        capture. ``finished_cb(succeeded, total)`` fires once when the batch
        completes (success or failure).
        """

        self._progress_cb = progress_cb
        self._finished_cb = finished_cb

    def start(self) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError:
            log.warning("APScheduler not installed; analysis scheduler disabled")
            return
        if self._scheduler is not None:
            return
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            self._tick,
            "interval",
            minutes=self.interval_minutes,
            id="analyze_hourly",
            next_run_time=datetime.now(),
            replace_existing=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        log.info(f"AnalysisScheduler started (interval={self.interval_minutes}m)")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            log.info("AnalysisScheduler stopped")

    def trigger_now(self, *, force: bool = False) -> None:
        """Run one tick immediately.

        ``force=True`` (used by the manual "Analyze now" menu item) bypasses
        the working-hours / idle gate entirely.
        """

        self._tick(force=force)

    def _tick(self, *, force: bool = False) -> None:
        if not force and not should_analyze_now(self.config):
            log.debug("Analysis tick: gate closed, skipping")
            return
        # Non-blocking lock: a second tick (e.g. manual click while the
        # scheduled hourly tick is already running) just skips rather than
        # piling up duplicate LLM calls + duplicate Analysis rows.
        if not self._tick_lock.acquire(blocking=False):
            log.info("Analysis tick: another tick is already running, skipping")
            return
        try:
            log.info(f"Analysis tick: running analyze_pending (force={force})")
            succeeded = 0
            total = 0
            seen_total = {"value": 0}

            def _progress(idx: int, tot: int, cap_id: int) -> None:
                seen_total["value"] = tot
                if self._progress_cb is not None:
                    self._progress_cb(idx, tot, cap_id)

            try:
                try:
                    result = self.job_fn(self.config, progress_cb=_progress)
                except TypeError:
                    # job_fn doesn't accept progress_cb (legacy callers / tests
                    # passing a plain ``lambda c: ...``). Fall back to the
                    # original single-arg call.
                    result = self.job_fn(self.config)
                succeeded = len(result) if isinstance(result, list) else 0
                total = seen_total["value"]
            except Exception as exc:
                log.error(f"Analysis tick failed: {exc}")
            finally:
                if self._finished_cb is not None:
                    try:
                        self._finished_cb(succeeded, total)
                    except Exception as exc:
                        log.warning(f"finished_cb raised: {exc}")
        finally:
            self._tick_lock.release()

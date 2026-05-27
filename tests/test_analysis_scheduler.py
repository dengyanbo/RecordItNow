"""Scheduler gating tests — pure logic, no APScheduler instance needed."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from rin.analysis.scheduler import AnalysisScheduler, should_analyze_now
from rin.config import RinConfig


def test_gate_off_when_hourly_disabled() -> None:
    cfg = RinConfig()
    cfg.analysis.hourly_enabled = False
    assert should_analyze_now(cfg) is False


def test_gate_always_open_when_require_idle_false() -> None:
    cfg = RinConfig()
    cfg.analysis.hourly_enabled = True
    cfg.analysis.require_idle_or_offhours = False
    # During working hours.
    assert should_analyze_now(cfg, now=datetime(2026, 5, 21, 14, 0)) is True


def test_gate_open_outside_working_hours() -> None:
    cfg = RinConfig()
    cfg.analysis.hourly_enabled = True
    cfg.analysis.require_idle_or_offhours = True
    with patch("rin.analysis.scheduler.is_idle", return_value=False):
        # Saturday 14:00 — outside working hours.
        assert should_analyze_now(cfg, now=datetime(2026, 5, 23, 14, 0)) is True


def test_gate_open_when_idle_during_working_hours() -> None:
    cfg = RinConfig()
    cfg.analysis.hourly_enabled = True
    cfg.analysis.require_idle_or_offhours = True
    with patch("rin.analysis.scheduler.is_idle", return_value=True):
        # Thursday 14:00 — within working hours but idle.
        assert should_analyze_now(cfg, now=datetime(2026, 5, 21, 14, 0)) is True


def test_gate_closed_during_active_working_hours() -> None:
    cfg = RinConfig()
    cfg.analysis.hourly_enabled = True
    cfg.analysis.require_idle_or_offhours = True
    with patch("rin.analysis.scheduler.is_idle", return_value=False):
        assert should_analyze_now(cfg, now=datetime(2026, 5, 21, 14, 0)) is False


def test_trigger_now_invokes_job_when_gate_open() -> None:
    cfg = RinConfig()
    cfg.analysis.require_idle_or_offhours = False
    seen: list = []

    sched = AnalysisScheduler(cfg, job_fn=lambda c: seen.append(c))
    sched.trigger_now()
    assert seen == [cfg]


def test_trigger_now_skips_when_gate_closed() -> None:
    cfg = RinConfig()
    cfg.analysis.hourly_enabled = False
    seen: list = []
    sched = AnalysisScheduler(cfg, job_fn=lambda c: seen.append(c))
    sched.trigger_now()
    assert seen == []


def test_job_exceptions_are_swallowed() -> None:
    cfg = RinConfig()
    cfg.analysis.require_idle_or_offhours = False

    def boom(_):
        raise RuntimeError("nope")

    sched = AnalysisScheduler(cfg, job_fn=boom)
    sched.trigger_now()  # must not raise


def test_concurrent_tick_is_serialized() -> None:
    """Issue R5: two simultaneous ticks must not both run analyze_pending."""

    import threading

    cfg = RinConfig()
    cfg.analysis.require_idle_or_offhours = False
    started = threading.Event()
    proceed = threading.Event()
    runs = []

    def slow_job(_cfg, **_kw):
        runs.append("start")
        started.set()
        # Hold the lock long enough for the second caller to attempt + skip.
        proceed.wait(timeout=2.0)
        runs.append("end")
        return []

    sched = AnalysisScheduler(cfg, job_fn=slow_job)
    t1 = threading.Thread(target=sched.trigger_now)
    t1.start()
    assert started.wait(timeout=1.0), "first tick never started"
    # Second invocation while the first is still inside the lock — must skip.
    t2 = threading.Thread(target=sched.trigger_now)
    t2.start()
    t2.join(timeout=1.0)
    assert not t2.is_alive(), "second tick blocked instead of skipping"
    proceed.set()
    t1.join(timeout=2.0)
    # The job ran exactly once.
    assert runs == ["start", "end"], f"expected one run, got: {runs}"

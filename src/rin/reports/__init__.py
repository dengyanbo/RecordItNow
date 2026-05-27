"""Report generation.

A report is a markdown document spanning a date range. We render two
flavours:

* **LLM-summarized** — when a provider is available, hand it the per-capture
  summaries with structure prompts and use the response as the body.
* **Offline fallback** — a Jinja2 template that just lists captures and their
  raw summaries (no narrative).
"""
from __future__ import annotations

from .generator import (
    ReportPeriod,
    daily_period,
    generate_report,
    list_captures_for_period,
    weekly_period,
)
from .scheduler import ReportsScheduler

__all__ = [
    "ReportPeriod",
    "ReportsScheduler",
    "daily_period",
    "generate_report",
    "list_captures_for_period",
    "weekly_period",
]

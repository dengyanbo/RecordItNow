"""Report full-text search tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rin.reports.search import search_reports
from rin.storage import db, init_db, session
from rin.storage.models import Report, ReportText

pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < (3, 9, 0),
    reason="requires SQLite FTS5",
)


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


def _seed_report(path: Path, when: datetime, kind: str, body: str) -> int:
    path.write_text(body, encoding="utf-8")
    with session() as s:
        report = Report(
            kind=kind,
            period_start=when,
            period_end=when + timedelta(days=1),
            markdown_path=str(path),
        )
        s.add(report)
        s.flush()
        report_id = report.id
        s.add(ReportText(report_id=report_id, body_text=body))
        return report_id


def test_search_reports_returns_best_match(tmp_path: Path) -> None:
    first_id = _seed_report(
        tmp_path / "daily-dragon.md",
        datetime(2026, 5, 28),
        "daily",
        "# Dragon report\n\nA dragon planning session with dragon diagrams and dragon notes.",
    )
    _seed_report(
        tmp_path / "daily-inbox.md",
        datetime(2026, 5, 29),
        "daily",
        "# Inbox\n\nEmail triage, changelog cleanup, and release prep.",
    )
    _seed_report(
        tmp_path / "weekly-dragon.md",
        datetime(2026, 6, 1),
        "weekly",
        "# Weekly review\n\nOne dragon mention inside a much longer retrospective about ops and testing.",
    )

    hits = search_reports("dragon")

    assert hits
    assert hits[0].report_id == first_id
    assert hits[0].kind == "daily"
    assert "dragon" in hits[0].snippet.lower()

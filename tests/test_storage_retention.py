"""Retention policy tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rin.storage import Capture, db, init_db, retention, session
from rin.storage import files as files_mod


@pytest.fixture(autouse=True)
def fresh_engine():
    db.reset()
    init_db()
    yield
    db.reset()


def test_compute_purgeable_filters_by_cutoff() -> None:
    now = datetime(2026, 5, 21, 12, 0, 0)
    old = Capture(id=1, kind="screenshot", started_at=now - timedelta(days=40))
    fresh = Capture(id=2, kind="video", started_at=now - timedelta(days=10))
    assert retention.compute_purgeable([old, fresh], now=now, retention_days=30) == [1]


def test_purge_marks_status_and_removes_folder() -> None:
    folder = files_mod.new_session_dir("shot", timestamp="20250101-100000")
    (folder / "monitor-0.png").write_text("fake")
    with session() as s:
        cap = Capture(
            kind="screenshot",
            folder=str(folder),
            started_at=datetime(2025, 1, 1, 10, 0, 0),
        )
        s.add(cap)
        s.flush()
        cap_id = cap.id

    now = datetime(2026, 5, 21, 12, 0, 0)
    with session() as s:
        report = retention.purge(s, now=now, retention_days=30)

    assert cap_id in report.capture_ids
    assert not folder.exists()
    with session() as s:
        cap = s.get(Capture, cap_id)
        assert cap is not None
        assert cap.status == "purged"


def test_purge_hard_delete_removes_row() -> None:
    folder = files_mod.new_session_dir("shot", timestamp="20250102-100000")
    with session() as s:
        cap = Capture(
            kind="screenshot",
            folder=str(folder),
            started_at=datetime(2025, 1, 2, 10, 0, 0),
        )
        s.add(cap)
        s.flush()
        cap_id = cap.id

    now = datetime(2026, 5, 21, 12, 0, 0)
    with session() as s:
        retention.purge(s, now=now, retention_days=30, keep_summaries=False)

    with session() as s:
        assert s.get(Capture, cap_id) is None

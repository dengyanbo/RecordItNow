"""CRUD + cascade smoke tests for the SQLAlchemy layer."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from rin import paths
from rin.storage import (
    Analysis,
    Capture,
    CaptureFile,
    db,
    init_db,
    session,
)


@pytest.fixture(autouse=True)
def fresh_engine():
    db.reset()
    init_db()
    yield
    db.reset()


def test_init_db_creates_file() -> None:
    assert paths.db_path().exists()


def test_pragmas_applied() -> None:
    with db.engine().connect() as conn:
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert fk == 1
    assert str(journal).lower() == "wal"


def test_capture_with_files_round_trip() -> None:
    with session() as s:
        c = Capture(kind="screenshot", folder="/tmp/cap1")
        c.files = [
            CaptureFile(
                monitor_index=0, path="m0.png", media_type="image/png", width=1920, height=1080
            ),
            CaptureFile(
                monitor_index=1, path="m1.png", media_type="image/png", width=1920, height=1080
            ),
        ]
        s.add(c)
    with session() as s:
        rows = s.scalars(select(Capture)).all()
        assert len(rows) == 1
        assert {f.monitor_index for f in rows[0].files} == {0, 1}


def test_cascade_delete_removes_children() -> None:
    with session() as s:
        c = Capture(kind="video", folder="/tmp/v1")
        c.analyses.append(
            Analysis(summary="hello", llm_provider="openai", llm_model="gpt-4o-mini")
        )
        s.add(c)
        s.flush()
        cap_id = c.id

    with session() as s:
        s.delete(s.get(Capture, cap_id))

    with session() as s:
        assert s.scalars(select(Analysis)).all() == []

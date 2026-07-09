"""Regression tests for the v1.3.0 hot-path indexes (O1)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from rin.storage import db, init_db
from rin.storage.migrations import migrate


def _indexes(engine) -> set[str]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }


def test_fresh_db_has_hot_indexes() -> None:
    db.reset()
    init_db()
    idx = _indexes(db.engine())
    assert "ix_captures_status_started_at" in idx
    assert "ix_buckets_status" in idx
    db.reset()


def test_hot_index_migration_on_legacy_db(tmp_path: Path) -> None:
    """A pre-v1.3 DB (captures + buckets, no hot indexes) gains them on migrate."""
    engine = create_engine(f"sqlite:///{tmp_path/'legacy.db'}", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE captures (id INTEGER PRIMARY KEY, status VARCHAR(32), started_at DATETIME)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE buckets (id INTEGER PRIMARY KEY, status VARCHAR(16))"
        )
        conn.exec_driver_sql("PRAGMA user_version = 7")

    migrate(engine)

    idx = _indexes(engine)
    assert "ix_captures_status_started_at" in idx
    assert "ix_buckets_status" in idx


def test_hot_index_migration_skips_missing_tables(tmp_path: Path) -> None:
    """Migration must not error on a bare DB missing the buckets table."""
    engine = create_engine(f"sqlite:///{tmp_path/'bare.db'}", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE captures (id INTEGER PRIMARY KEY, status VARCHAR(32), started_at DATETIME)"
        )
        conn.exec_driver_sql("PRAGMA user_version = 7")

    migrate(engine)  # must not raise

    idx = _indexes(engine)
    assert "ix_captures_status_started_at" in idx
    assert "ix_buckets_status" not in idx  # buckets table absent → skipped

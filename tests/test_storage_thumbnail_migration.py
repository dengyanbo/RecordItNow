from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from rin.storage.migrations import CURRENT_VERSION, migrate


def _make_legacy_engine(tmp_path: Path, *, include_thumbnail: bool):
    db_path = tmp_path / ("fresh.db" if include_thumbnail else "legacy.db")
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    thumbnail_sql = ", thumbnail_path TEXT" if include_thumbnail else ""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE captures ("
            "id INTEGER PRIMARY KEY, "
            "kind VARCHAR(16), "
            "status VARCHAR(32), "
            "started_at DATETIME, "
            "ended_at DATETIME, "
            "duration_ms INTEGER, "
            "file_size BIGINT, "
            "folder TEXT, "
            f"notes TEXT{thumbnail_sql}"
            ")"
        )
        conn.exec_driver_sql("PRAGMA user_version = 1")
    return engine


def test_thumbnail_migration_adds_column(tmp_path: Path) -> None:
    engine = _make_legacy_engine(tmp_path, include_thumbnail=False)

    migrate(engine)

    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(captures)").fetchall()
        }
        version = conn.execute(text("PRAGMA user_version")).scalar()

    assert "thumbnail_path" in columns
    assert version == CURRENT_VERSION


def test_thumbnail_migration_is_safe_when_column_already_exists(tmp_path: Path) -> None:
    engine = _make_legacy_engine(tmp_path, include_thumbnail=True)

    migrate(engine)

    with engine.connect() as conn:
        columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(captures)").fetchall()]
        version = conn.execute(text("PRAGMA user_version")).scalar()

    assert columns.count("thumbnail_path") == 1
    assert version == CURRENT_VERSION

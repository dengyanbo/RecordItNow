"""Lightweight schema migration runner.

Schema version is tracked via SQLite's ``PRAGMA user_version``. Each
migration is a ``(target_version, sql_or_callable)`` tuple appended to
``MIGRATIONS``. ``Base.metadata.create_all`` provides the version-0
baseline; this module only handles deltas added in later phases.

.. note::

    SQL strings in :data:`MIGRATIONS` are split on ``;`` to allow multiple
    statements per entry, but the split is **naive** (string literals
    containing ``;`` would be incorrectly split). For any migration whose
    SQL might contain a semicolon inside a quoted string, register a
    *callable* instead and run statements explicitly with
    ``conn.exec_driver_sql``. The report-search migration uses this pattern
    for its FTS5 trigger bodies.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _add_capture_thumbnail_path(engine: Engine) -> None:
    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(captures)").fetchall()
        }
        if "thumbnail_path" not in columns:
            conn.execute(text("ALTER TABLE captures ADD COLUMN thumbnail_path TEXT"))


def _migrate_reports_fts(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS report_text (
                    report_id INTEGER PRIMARY KEY,
                    body TEXT NOT NULL,
                    FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE
                )
                """
            )
        )
        if sqlite3.sqlite_version_info < (3, 9, 0):
            return
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(body, content='report_text', content_rowid='report_id')"
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS report_text_ai AFTER INSERT ON report_text BEGIN
                INSERT INTO reports_fts(rowid, body) VALUES (new.report_id, new.body);
            END
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS report_text_ad AFTER DELETE ON report_text BEGIN
                INSERT INTO reports_fts(reports_fts, rowid, body) VALUES ('delete', old.report_id, old.body);
            END
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS report_text_au AFTER UPDATE ON report_text BEGIN
                INSERT INTO reports_fts(reports_fts, rowid, body) VALUES ('delete', old.report_id, old.body);
                INSERT INTO reports_fts(rowid, body) VALUES (new.report_id, new.body);
            END
            """
        )
        conn.exec_driver_sql("INSERT INTO reports_fts(reports_fts) VALUES ('rebuild')")


# (target_version, sql_or_fn). ``fn`` receives the Engine and runs inside its own transaction.
MIGRATIONS: list[tuple[int, str | Callable[[Engine], None]]] = [
    # v0.5.0: skill-driven bucket categorization (see rin.skills).
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS buckets (
            id           INTEGER PRIMARY KEY,
            skill_name   VARCHAR(64)  NOT NULL,
            key          VARCHAR(256) NOT NULL,
            title        TEXT         NOT NULL,
            extra_json   TEXT,
            status       VARCHAR(16)  NOT NULL DEFAULT 'active',
            opened_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at    DATETIME,
            archive_path TEXT,
            UNIQUE (skill_name, key)
        );
        CREATE INDEX IF NOT EXISTS ix_buckets_skill_name ON buckets (skill_name);
        CREATE INDEX IF NOT EXISTS ix_buckets_key        ON buckets (key);
        CREATE INDEX IF NOT EXISTS ix_buckets_opened_at  ON buckets (opened_at);
        CREATE TABLE IF NOT EXISTS capture_buckets (
            capture_id INTEGER NOT NULL,
            bucket_id  INTEGER NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (capture_id, bucket_id),
            FOREIGN KEY (capture_id) REFERENCES captures (id) ON DELETE CASCADE,
            FOREIGN KEY (bucket_id)  REFERENCES buckets (id)  ON DELETE CASCADE
        );
        """,
    ),
    (2, _add_capture_thumbnail_path),
    # v0.4.0: report full-text search index backed by report_text + FTS5.
    (3, _migrate_reports_fts),
]

CURRENT_VERSION = max((m[0] for m in MIGRATIONS), default=0)


def get_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA user_version")).scalar() or 0


def set_version(engine: Engine, version: int) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {int(version)}"))


def migrate(engine: Engine) -> None:
    """Apply any pending migrations. Idempotent."""

    current = get_version(engine)
    if current >= CURRENT_VERSION:
        return
    for target, op in MIGRATIONS:
        if target <= current:
            continue
        if callable(op):
            op(engine)
        else:
            with engine.begin() as conn:
                for stmt in str(op).split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(text(stmt))
        set_version(engine, target)

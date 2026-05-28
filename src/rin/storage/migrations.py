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
    ``conn.exec_driver_sql``. The current migration list is empty, so this
    only matters for future entries.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

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

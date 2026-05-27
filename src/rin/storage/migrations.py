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
    # e.g. (1, "ALTER TABLE captures ADD COLUMN auto_tagged INTEGER DEFAULT 0"),
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

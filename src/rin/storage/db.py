"""Engine + session factory for RIN's SQLite database.

``init_db()`` is idempotent: call it at startup. It creates tables,
applies pending migrations, and sets WAL journal mode so capture writes
don't block analysis reads.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .. import paths
from . import migrations
from .models import Base

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _make_engine(url: str | None = None) -> Engine:
    url = url or f"sqlite:///{paths.db_path().as_posix()}"
    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.close()

    return engine


def init_db(*, url: str | None = None) -> Engine:
    """Create tables (if missing), apply migrations, and prepare the session factory."""

    global _engine, _session_factory
    _engine = _make_engine(url)
    Base.metadata.create_all(_engine)
    migrations.migrate(_engine)
    _session_factory = sessionmaker(_engine, expire_on_commit=False, future=True)
    return _engine


def engine() -> Engine:
    if _engine is None:
        init_db()
    assert _engine is not None
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    """Context-managed session that commits on success and rolls back on error."""

    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    s = _session_factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reset() -> None:
    """Drop the cached engine and session factory. Used by tests."""

    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None

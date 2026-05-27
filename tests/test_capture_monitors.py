"""Monitor enumeration smoke tests.

We don't require multiple monitors — these tests work on any machine
with at least one display. CI without a display will simply skip.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from rin.capture.monitors import MonitorInfo, enumerate_monitors, refresh_monitor_records
from rin.storage import init_db, session
from rin.storage.models import Monitor


@pytest.fixture(autouse=True)
def fresh_db():
    from rin.storage import db

    db.reset()
    init_db()
    yield
    db.reset()


def test_enumerate_returns_at_least_one_monitor_or_empty() -> None:
    infos = enumerate_monitors()
    # On a headless host this is allowed to be empty; on a workstation it should not be.
    assert isinstance(infos, list)
    for info in infos:
        assert isinstance(info, MonitorInfo)
        assert info.width > 0
        assert info.height > 0
        assert info.bbox[2] == info.x + info.width


def test_refresh_monitor_records_persists_rows() -> None:
    fake = [
        MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=1920, height=1080, is_primary=True),
        MonitorInfo(index=2, name="monitor-2", x=1920, y=0, width=1920, height=1080, is_primary=False),
    ]
    refresh_monitor_records(fake)
    with session() as s:
        rows = s.scalars(select(Monitor)).all()
    by_name = {r.device_name: r for r in rows}
    assert by_name["monitor-1"].is_primary is True
    assert by_name["monitor-2"].x == 1920


def test_refresh_is_idempotent() -> None:
    fake = [
        MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=1920, height=1080, is_primary=True)
    ]
    refresh_monitor_records(fake)
    # Geometry changes.
    fake_updated = [
        MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=2560, height=1440, is_primary=True)
    ]
    refresh_monitor_records(fake_updated)
    with session() as s:
        row = s.scalars(select(Monitor).where(Monitor.device_name == "monitor-1")).one()
    assert row.width == 2560
    assert row.height == 1440

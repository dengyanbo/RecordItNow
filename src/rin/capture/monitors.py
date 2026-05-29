"""Physical-monitor enumeration via ``mss``.

We use ``mss`` (already a capture dependency) rather than the win32 API
because mss already abstracts mixed-DPI sub-rectangles. ``mss().monitors``
returns index 0 = virtual desktop bbox followed by one entry per
physical monitor; we skip index 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ..storage import session
from ..storage.models import Monitor
from ..utils.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class MonitorInfo:
    index: int
    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """``(left, top, right, bottom)`` for ffmpeg/mss region capture."""

        return (self.x, self.y, self.x + self.width, self.y + self.height)


def _build_info(idx: int, mon: dict, virtual: dict) -> MonitorInfo:
    name = f"monitor-{idx}"
    is_primary = mon.get("left") == 0 and mon.get("top") == 0 and idx == 1
    return MonitorInfo(
        index=idx,
        name=name,
        x=int(mon.get("left", 0)),
        y=int(mon.get("top", 0)),
        width=int(mon.get("width", 0)),
        height=int(mon.get("height", 0)),
        is_primary=bool(is_primary),
    )


def enumerate_monitors() -> list[MonitorInfo]:
    """Return per-physical-monitor info. Skips the virtual desktop pseudo-entry."""

    try:
        import mss
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("mss package not installed") from exc

    # ``mss.MSS`` is the platform-dispatching factory class since v10.2;
    # the older ``mss.mss()`` helper is deprecated and emits a warning
    # on every call.
    with mss.MSS() as sct:
        monitors = sct.monitors
        if len(monitors) < 2:
            return []
        virtual = monitors[0]
        return [_build_info(i, m, virtual) for i, m in enumerate(monitors[1:], start=1)]


def refresh_monitor_records(monitors: list[MonitorInfo] | None = None) -> list[MonitorInfo]:
    """Persist current monitor geometry into the DB (upsert by ``device_name``)."""

    infos = monitors if monitors is not None else enumerate_monitors()
    with session() as s:
        existing: dict[str, Monitor] = {
            m.device_name: m for m in s.scalars(select(Monitor)).all()
        }
        for info in infos:
            row = existing.get(info.name)
            if row is None:
                row = Monitor(device_name=info.name)
                s.add(row)
            row.x = info.x
            row.y = info.y
            row.width = info.width
            row.height = info.height
            row.is_primary = info.is_primary
    return infos


def get_mss_grabber() -> Any:  # pragma: no cover - thin alias
    """Return a fresh ``mss.MSS()`` grabber. Wrapped for tests to patch."""

    import mss

    return mss.MSS()

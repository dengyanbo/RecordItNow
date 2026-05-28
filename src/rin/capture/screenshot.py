"""Multi-monitor screenshot pipeline.

``capture_screenshot()`` is synchronous and intended to be called from a
worker thread (the gesture recognizer should never block the UI). It:

1. Allocates a fresh ``captures/YYYY/MM/DD/<ts>-shot/`` folder.
2. Grabs every physical monitor with ``mss`` and writes ``monitor-N.png``.
3. Inserts ``Capture`` + per-monitor ``CaptureFile`` rows.
4. Returns the persisted :class:`~rin.storage.models.Capture`.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..storage import session
from ..storage.files import new_session_dir
from ..storage.models import Capture, CaptureFile
from ..utils.logging import get_logger
from ..utils.thumbnail import make_thumbnail
from .monitors import MonitorInfo, enumerate_monitors

log = get_logger(__name__)


def capture_screenshot(
    *,
    monitors: list[MonitorInfo] | None = None,
    grabber_factory: Any | None = None,
) -> int:
    """Capture every monitor to PNG. Returns the new ``Capture.id``.

    ``grabber_factory`` is for tests — pass a callable returning an mss-like
    context manager. By default we use the real ``mss.mss()``.
    """

    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d-%H%M%S")
    folder = new_session_dir("shot", timestamp=timestamp)

    infos = monitors if monitors is not None else enumerate_monitors()
    if not infos:
        log.warning("No physical monitors found; aborting screenshot")
        raise RuntimeError("No physical monitors detected")

    if grabber_factory is None:
        import mss

        grabber_factory = mss.mss

    paths: list[tuple[MonitorInfo, Path, int]] = []
    capture_thumbnail: Path | None = None
    with grabber_factory() as sct:
        for info in infos:
            region = {
                "left": info.x,
                "top": info.y,
                "width": info.width,
                "height": info.height,
            }
            shot = sct.grab(region)
            out = folder / f"monitor-{info.index}.png"
            _save_png(shot, out)
            thumbnail = _write_thumbnail(out)
            if capture_thumbnail is None and thumbnail is not None:
                capture_thumbnail = thumbnail
            paths.append((info, out, out.stat().st_size))

    total_bytes = sum(size for _, _, size in paths)
    ended_at = datetime.now()
    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="captured",
            folder=str(folder),
            thumbnail_path=str(capture_thumbnail) if capture_thumbnail else None,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            file_size=total_bytes,
        )
        cap.files = [
            CaptureFile(
                monitor_index=info.index,
                path=str(path),
                media_type="image/png",
                width=info.width,
                height=info.height,
                file_size=size,
            )
            for info, path, size in paths
        ]
        s.add(cap)
        s.flush()
        cap_id = cap.id

    log.info(f"Screenshot captured: {len(paths)} monitor(s), {total_bytes} bytes → capture_id={cap_id}")
    return cap_id


def _write_thumbnail(src: Path) -> Path | None:
    thumb = src.with_suffix(".jpg")
    try:
        return make_thumbnail(src, thumb)
    except Exception as exc:
        log.warning(f"Thumbnail generation failed for {src.name}: {exc}")
        return None


def _save_png(shot: Any, dest: Path) -> None:
    """Write an ``mss.ScreenShot`` (or a duck-typed mock) to disk as PNG."""

    if hasattr(shot, "save"):
        shot.save(str(dest))
        return
    # mss returns a ScreenShot which has .rgb and .size; fall back to mss.tools.to_png.
    try:
        from mss.tools import to_png
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("mss.tools not available") from exc
    size = getattr(shot, "size", None)
    raw = getattr(shot, "rgb", None) or getattr(shot, "raw", None)
    if size is None or raw is None:
        raise RuntimeError("Screenshot object missing 'size' or 'rgb' attributes")
    to_png(raw, size, output=str(dest))

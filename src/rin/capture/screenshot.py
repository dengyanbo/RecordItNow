"""Multi-monitor screenshot pipeline.

``capture_screenshot()`` is synchronous and intended to be called from a
worker thread (the gesture recognizer should never block the UI). It:

1. Allocates a fresh ``captures/YYYY/MM/DD/<ts>-shot/`` folder.
2. Grabs every physical monitor with ``mss`` and writes ``monitor-N.jpg``
   (or ``monitor-N.png`` when ``image_format="png"``).
3. Inserts ``Capture`` + per-monitor ``CaptureFile`` rows.
4. Returns the persisted :class:`~rin.storage.models.Capture`.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..storage import session
from ..storage.files import new_session_dir
from ..storage.models import Capture, CaptureFile
from ..utils.encryption import CaptureCipher
from ..utils.logging import get_logger
from ..utils.thumbnail import make_thumbnail, make_thumbnail_from_image
from .monitors import MonitorInfo, enumerate_monitors

log = get_logger(__name__)


def capture_screenshot(
    *,
    monitors: list[MonitorInfo] | None = None,
    grabber_factory: Any | None = None,
    encrypt_at_rest: bool = False,
    cipher: CaptureCipher | None = None,
    image_format: str = "png",
    jpeg_quality: int = 85,
    on_grabbed: Callable[[], None] | None = None,
) -> int:
    """Capture every monitor. Returns the new ``Capture.id``.

    ``image_format`` is ``"jpeg"`` or ``"png"``. JPEG encodes far faster
    (and content-independently), which is the default in production; PNG is
    lossless. ``grabber_factory`` is for tests — pass a callable returning
    an mss-like context manager. By default we use the real ``mss.MSS``.

    ``on_grabbed`` is invoked *once*, right after every monitor has been
    grabbed into memory but **before** the (slow) encode. The screenshot
    feedback (toast) is fired from there so a tap feels instant regardless
    of screen content or monitor count. It must not raise; exceptions are
    swallowed so feedback can never break a capture.
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

        grabber_factory = mss.MSS

    effective_cipher = cipher or (CaptureCipher() if encrypt_at_rest else None)
    should_encrypt = (
        encrypt_at_rest
        and effective_cipher is not None
        and effective_cipher.is_available()
    )

    fmt = (image_format or "png").lower()
    if fmt == "jpg":
        fmt = "jpeg"
    ext = "jpg" if fmt == "jpeg" else "png"
    media_type = "image/jpeg" if fmt == "jpeg" else "image/png"

    # 1) Grab every monitor into memory first. Grabbing is fast (~1-5 ms per
    #    monitor); the PNG/JPEG *encode* is the slow part, so we defer it
    #    until after the user has been given feedback.
    grabbed: list[tuple[MonitorInfo, Any]] = []
    with grabber_factory() as sct:
        for info in infos:
            region = {
                "left": info.x,
                "top": info.y,
                "width": info.width,
                "height": info.height,
            }
            grabbed.append((info, sct.grab(region)))

    # 2) Fire the "captured" feedback now, before the encode, so the tap
    #    feels instant. Never let a feedback error abort the capture.
    if on_grabbed is not None:
        try:
            on_grabbed()
        except Exception as exc:  # pragma: no cover - defensive
            log.debug(f"on_grabbed feedback callback raised: {exc}")

    # 3) Encode + thumbnail + optional encryption (the slow part).
    paths: list[tuple[MonitorInfo, Path, int]] = []
    capture_thumbnail: Path | None = None
    for info, shot in grabbed:
        out = folder / f"monitor-{info.index}.{ext}"
        image = _encode_shot(shot, out, fmt=fmt, quality=jpeg_quality)
        final_path = out
        if should_encrypt:
            assert effective_cipher is not None
            final_path = out.with_name(f"{out.name}.enc")
            effective_cipher.encrypt_file(out, final_path)
            out.unlink()
        else:
            thumbnail = _write_thumbnail(out, image=image)
            if capture_thumbnail is None and thumbnail is not None:
                capture_thumbnail = thumbnail
        paths.append((info, final_path, final_path.stat().st_size))

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
                media_type=media_type,
                width=info.width,
                height=info.height,
                file_size=size,
            )
            for info, path, size in paths
        ]
        s.add(cap)
        s.flush()
        cap_id = cap.id

    log.info(
        f"Screenshot captured: {len(paths)} monitor(s) [{fmt}], "
        f"{total_bytes} bytes → capture_id={cap_id}"
    )
    return cap_id


def _write_thumbnail(src: Path, image: Any | None = None) -> Path | None:
    # Collision-safe name: a JPEG capture is ``monitor-N.jpg``, so the
    # thumbnail must NOT be ``monitor-N.jpg`` — that would overwrite the
    # capture. ``monitor-N.thumb.jpg`` is distinct for both png and jpeg.
    thumb = src.with_name(f"{src.stem}.thumb.jpg")
    try:
        if image is not None:
            return make_thumbnail_from_image(image, thumb)
        return make_thumbnail(src, thumb)
    except Exception as exc:
        log.warning(f"Thumbnail generation failed for {src.name}: {exc}")
        return None


def _pil_from_shot(shot: Any) -> Any | None:
    """Build a PIL RGB image from an mss ``ScreenShot``.

    Returns ``None`` when the object doesn't expose raw pixels (e.g. a
    lightweight test stub that only implements ``.save()``).
    """

    rgb = getattr(shot, "rgb", None)
    size = getattr(shot, "size", None)
    if rgb is None or size is None:
        return None
    from PIL import Image

    return Image.frombytes("RGB", (int(size[0]), int(size[1])), rgb)


def _encode_shot(shot: Any, dest: Path, *, fmt: str, quality: int) -> Any | None:
    """Write a grabbed frame to ``dest`` in ``fmt``.

    Returns the PIL image used for JPEG (so the thumbnail can be derived
    from it without re-reading the file) or ``None`` for the PNG / stub
    ``.save()`` path.
    """

    if fmt == "jpeg":
        image = _pil_from_shot(shot)
        if image is not None:
            image.save(dest, format="JPEG", quality=quality)
            return image
        # Stub shot without raw pixels — fall back to its own writer.
        _save_png(shot, dest)
        return None
    _save_png(shot, dest)
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

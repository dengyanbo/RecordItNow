"""Screenshot format (JPEG default) + feedback-decoupling tests.

Covers the v1.4.0 capture-latency work:
* JPEG is the default encoding and produces ``.jpg`` + ``image/jpeg``.
* The thumbnail never overwrites a JPEG capture (collision-safe name).
* PNG remains fully supported.
* ``on_grabbed`` fires exactly once, before any encode (instant feedback).
* ``CaptureService.take_screenshot`` forwards the configured format,
  quality, and the ``on_grabbed`` callback.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from rin.capture import screenshot as screenshot_mod
from rin.capture.monitors import MonitorInfo
from rin.capture.screenshot import capture_screenshot
from rin.capture.service import CaptureService
from rin.config import RinConfig
from rin.storage import db, init_db, session
from rin.storage.models import Capture, CaptureFile


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


class _RichShot:
    """mss-like ScreenShot: exposes ``.rgb`` + ``.size`` (the real encode
    path) as well as ``.save()`` (the PNG stub path)."""

    def __init__(self, w: int, h: int) -> None:
        self.size = (w, h)
        # deterministic, non-uniform pixels so JPEG yields real output
        self.rgb = bytes((i * 7) % 256 for i in range(w * h * 3))

    def save(self, path: str) -> None:
        Image.frombytes("RGB", self.size, self.rgb).save(path, format="PNG")


class _RichGrabber:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def grab(self, region: dict) -> _RichShot:
        return _RichShot(region["width"], region["height"])


def _mon(index: int = 1, w: int = 80, h: int = 60) -> MonitorInfo:
    return MonitorInfo(
        index=index, name=f"monitor-{index}", x=0, y=0,
        width=w, height=h, is_primary=(index == 1),
    )


def test_jpeg_is_default_writes_jpg_and_media_type() -> None:
    cap_id = capture_screenshot(
        monitors=[_mon()], grabber_factory=lambda: _RichGrabber(), image_format="jpeg"
    )
    with session() as s:
        files = s.scalars(select(CaptureFile).where(CaptureFile.capture_id == cap_id)).all()
        assert len(files) == 1
        f = files[0]
        assert f.media_type == "image/jpeg"
        p = Path(f.path)
        assert p.suffix == ".jpg"
        assert p.read_bytes()[:2] == b"\xff\xd8"  # JPEG SOI magic


def test_jpeg_thumbnail_does_not_overwrite_capture() -> None:
    cap_id = capture_screenshot(
        monitors=[_mon()], grabber_factory=lambda: _RichGrabber(), image_format="jpeg"
    )
    with session() as s:
        cap = s.get(Capture, cap_id)
        capture_file = Path(cap.files[0].path)   # monitor-1.jpg
        thumb = Path(cap.thumbnail_path)         # monitor-1.thumb.jpg

    assert capture_file.name == "monitor-1.jpg"
    assert thumb.name == "monitor-1.thumb.jpg"
    assert capture_file != thumb
    assert capture_file.exists() and thumb.exists()

    with Image.open(capture_file) as im:
        assert im.size == (80, 60)               # full-res capture intact
    with Image.open(thumb) as im:
        assert im.size[0] <= 240                 # thumbnail is downscaled


def test_png_format_still_supported() -> None:
    cap_id = capture_screenshot(
        monitors=[_mon()], grabber_factory=lambda: _RichGrabber(), image_format="png"
    )
    with session() as s:
        f = s.get(Capture, cap_id).files[0]
        assert f.media_type == "image/png"
        p = Path(f.path)
        assert p.suffix == ".png"
        assert p.read_bytes().startswith(b"\x89PNG")


def test_on_grabbed_fires_once_before_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    real_encode = screenshot_mod._encode_shot

    def _tracking_encode(*args, **kwargs):
        order.append("encode")
        return real_encode(*args, **kwargs)

    monkeypatch.setattr(screenshot_mod, "_encode_shot", _tracking_encode)

    capture_screenshot(
        monitors=[_mon(1), _mon(2)],
        grabber_factory=lambda: _RichGrabber(),
        image_format="jpeg",
        on_grabbed=lambda: order.append("grabbed"),
    )

    assert order.count("grabbed") == 1
    assert order[0] == "grabbed"        # feedback fires BEFORE any encode
    assert order.count("encode") == 2   # one encode per monitor, all after


def test_take_screenshot_forwards_format_quality_and_on_grabbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_capture_screenshot(*, monitors=None, encrypt_at_rest=False, cipher=None,
                                image_format="png", jpeg_quality=85, on_grabbed=None):
        seen["image_format"] = image_format
        seen["jpeg_quality"] = jpeg_quality
        if on_grabbed is not None:
            on_grabbed()
        return 7

    monkeypatch.setattr("rin.capture.service.capture_screenshot", fake_capture_screenshot)
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda _b: True)

    cfg = RinConfig()  # default screenshot_format == "jpeg"
    svc = CaptureService(cfg)
    svc._monitors = [_mon()]

    fired = {"cb": False}
    cap_id = svc.take_screenshot(on_grabbed=lambda: fired.__setitem__("cb", True))

    assert cap_id == 7
    assert seen["image_format"] == "jpeg"
    assert seen["jpeg_quality"] == 85
    assert fired["cb"] is True

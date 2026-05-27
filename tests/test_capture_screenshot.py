"""Screenshot pipeline tests with a stubbed mss grabber."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from sqlalchemy import select

from rin.capture.monitors import MonitorInfo
from rin.capture.screenshot import capture_screenshot
from rin.storage import init_db, session
from rin.storage.models import Capture, CaptureFile


@pytest.fixture(autouse=True)
def fresh_db():
    from rin.storage import db

    db.reset()
    init_db()
    yield
    db.reset()


def _tiny_png_bytes(width: int = 2, height: int = 2) -> bytes:
    """Return the bytes of a minimal valid PNG without importing Pillow."""

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    compressed = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


class _FakeShot:
    def __init__(self, dest_bytes: bytes) -> None:
        self._bytes = dest_bytes

    def save(self, path: str) -> None:
        Path(path).write_bytes(self._bytes)


class _FakeGrabber:
    def __init__(self, monitors: list[dict]) -> None:
        self.monitors = monitors

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def grab(self, region: dict) -> _FakeShot:
        return _FakeShot(_tiny_png_bytes(width=2, height=2))


def test_capture_screenshot_writes_files_and_db_rows() -> None:
    monitors = [
        MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=1920, height=1080, is_primary=True),
        MonitorInfo(index=2, name="monitor-2", x=1920, y=0, width=1920, height=1080, is_primary=False),
    ]
    factory = lambda: _FakeGrabber([])  # noqa: E731 - dummy factory
    cap_id = capture_screenshot(monitors=monitors, grabber_factory=factory)
    assert isinstance(cap_id, int)

    with session() as s:
        cap = s.get(Capture, cap_id)
        assert cap is not None
        assert cap.kind == "screenshot"
        assert cap.status == "captured"
        files = s.scalars(select(CaptureFile).where(CaptureFile.capture_id == cap_id)).all()
        assert len(files) == 2
        for f in files:
            p = Path(f.path)
            assert p.exists()
            assert p.read_bytes().startswith(b"\x89PNG")


def test_capture_screenshot_with_no_monitors_raises() -> None:
    with pytest.raises(RuntimeError):
        capture_screenshot(monitors=[], grabber_factory=lambda: _FakeGrabber([]))

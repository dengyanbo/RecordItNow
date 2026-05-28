"""Benchmark the screenshot capture-all path (target: ≤200ms on a 1-monitor mock)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from rin.capture.monitors import MonitorInfo
from rin.capture.screenshot import capture_screenshot
from rin.storage import db, init_db


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


def _tiny_png_bytes(width: int = 320, height: int = 240) -> bytes:
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
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
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def save(self, path: str) -> None:
        Path(path).write_bytes(self._payload)


class _FakeGrabber:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def grab(self, _region: dict) -> _FakeShot:
        return _FakeShot(self._payload)


@pytest.mark.benchmark(group="screenshot")
def test_capture_screenshot_benchmark(benchmark) -> None:
    """target: ≤200ms on a 1-monitor mock."""

    init_db()
    monitor = MonitorInfo(
        index=1,
        name="monitor-1",
        x=0,
        y=0,
        width=1920,
        height=1080,
        is_primary=True,
    )
    payload = _tiny_png_bytes()
    capture_ids: list[int] = []

    def run_capture() -> int:
        capture_id = capture_screenshot(
            monitors=[monitor],
            grabber_factory=lambda: _FakeGrabber(payload),
        )
        capture_ids[:] = [capture_id]
        return capture_id

    benchmark.pedantic(run_capture, rounds=5, iterations=1, warmup_rounds=1)
    assert capture_ids and capture_ids[0] > 0

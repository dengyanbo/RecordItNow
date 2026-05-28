from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from sqlalchemy import select

from rin import paths
from rin.capture.monitors import MonitorInfo
from rin.capture.screenshot import capture_screenshot as real_capture_screenshot
from rin.capture.service import CaptureService
from rin.config import RinConfig
from rin.storage import init_db, session
from rin.storage.models import CaptureFile
from rin.utils.encryption import CaptureCipher


@pytest.fixture(autouse=True)
def fresh_db():
    from rin.storage import db

    db.reset()
    init_db()
    yield
    db.reset()


def _tiny_png_bytes(width: int = 2, height: int = 2) -> bytes:
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


PNG_BYTES = _tiny_png_bytes()


class _FakeShot:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def save(self, path: str) -> None:
        Path(path).write_bytes(self._payload)


class _FakeGrabber:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def grab(self, _region: dict) -> _FakeShot:
        return _FakeShot(PNG_BYTES)


def _service_with_monitors(*, encrypt_at_rest: bool) -> CaptureService:
    cfg = RinConfig()
    cfg.privacy.encrypt_at_rest = encrypt_at_rest
    svc = CaptureService(cfg)
    svc._monitors = [
        MonitorInfo(
            index=1,
            name="monitor-1",
            x=0,
            y=0,
            width=1920,
            height=1080,
            is_primary=True,
        )
    ]
    return svc


def _patch_capture_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda _blacklist: True)

    def fake_capture_screenshot(*, monitors=None, encrypt_at_rest=False, cipher=None):
        return real_capture_screenshot(
            monitors=monitors,
            grabber_factory=lambda: _FakeGrabber(),
            encrypt_at_rest=encrypt_at_rest,
            cipher=cipher,
        )

    monkeypatch.setattr("rin.capture.service.capture_screenshot", fake_capture_screenshot)


def test_take_screenshot_produces_encrypted_pngs_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_capture_flow(monkeypatch)
    svc = _service_with_monitors(encrypt_at_rest=True)

    cap_id = svc.take_screenshot()

    assert isinstance(cap_id, int)
    assert (paths.root_dir() / ".master.key.enc").exists()
    with session() as s:
        files = s.scalars(select(CaptureFile).where(CaptureFile.capture_id == cap_id)).all()
    assert len(files) == 1
    enc_path = Path(files[0].path)
    assert enc_path.name.endswith(".png.enc")
    assert enc_path.exists()
    assert not enc_path.with_suffix("").exists()
    assert CaptureCipher().decrypt_bytes(enc_path.read_bytes()) == PNG_BYTES


def test_take_screenshot_keeps_plain_pngs_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_capture_flow(monkeypatch)
    svc = _service_with_monitors(encrypt_at_rest=False)

    cap_id = svc.take_screenshot()

    assert isinstance(cap_id, int)
    assert not (paths.root_dir() / ".master.key.enc").exists()
    with session() as s:
        files = s.scalars(select(CaptureFile).where(CaptureFile.capture_id == cap_id)).all()
    assert len(files) == 1
    png_path = Path(files[0].path)
    assert png_path.suffix == ".png"
    assert png_path.read_bytes() == PNG_BYTES

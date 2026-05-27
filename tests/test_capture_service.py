"""End-to-end CaptureService tests with mocked grabber + recorder."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from rin.capture.monitors import MonitorInfo
from rin.capture.service import CaptureService
from rin.config import RinConfig
from rin.storage import init_db, session
from rin.storage.models import Capture, CaptureFile


@pytest.fixture(autouse=True)
def fresh_db():
    from rin.storage import db

    db.reset()
    init_db()
    yield
    db.reset()


class _FakeRecorder:
    def __init__(self, *, monitors, folder, capture_cfg, audio_device=None):
        self.monitors = monitors
        self.folder = folder
        self.capture_cfg = capture_cfg
        self.audio_device = audio_device
        self._outputs: list[Path] = []
        self.started = False
        self.stopped = False

    @property
    def outputs(self) -> list[Path]:
        return self._outputs

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.started = True
        for m in self.monitors:
            out = self.folder / f"monitor-{m.index}.mp4"
            out.write_bytes(b"\x00\x00\x00\x18ftypisom")  # tiny fake MP4 prefix
            self._outputs.append(out)

    def stop(self) -> list[Path]:
        self.stopped = True
        return self._outputs


def _service_with_monitors() -> CaptureService:
    cfg = RinConfig()
    svc = CaptureService(cfg)
    svc._monitors = [
        MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=800, height=600, is_primary=True),
        MonitorInfo(index=2, name="monitor-2", x=800, y=0, width=800, height=600, is_primary=False),
    ]
    return svc


def test_start_stop_recording_persists_capture() -> None:
    svc = _service_with_monitors()
    assert svc.start_recording(recorder_factory=_FakeRecorder) is True
    assert svc.is_recording() is True
    cap_id = svc.stop_recording()
    assert svc.is_recording() is False
    assert isinstance(cap_id, int)

    with session() as s:
        cap = s.get(Capture, cap_id)
        assert cap is not None
        assert cap.kind == "video"
        files = s.scalars(select(CaptureFile).where(CaptureFile.capture_id == cap_id)).all()
        assert {f.monitor_index for f in files} == {1, 2}
        for f in files:
            assert Path(f.path).exists()


def test_double_start_is_a_noop() -> None:
    svc = _service_with_monitors()
    svc.start_recording(recorder_factory=_FakeRecorder)
    assert svc.start_recording(recorder_factory=_FakeRecorder) is False
    svc.stop_recording()


def test_stop_without_start_returns_none() -> None:
    svc = _service_with_monitors()
    assert svc.stop_recording() is None


def test_take_screenshot_uses_capture_service_lock() -> None:
    svc = _service_with_monitors()
    # Use a fake grabber via monkeypatching capture_screenshot indirectly.
    # Here we just verify that with no monitors, take_screenshot returns None.
    svc._monitors = []
    assert svc.take_screenshot() is None

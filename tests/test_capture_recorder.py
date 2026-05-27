"""FFmpeg recorder tests using a mocked subprocess.

The real ffmpeg binary is not required for these tests; we substitute a
fake ``Popen`` class that records the command line and simulates a
graceful exit when sent the ``q`` byte.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

from rin.capture.monitors import MonitorInfo
from rin.capture.recorder import VideoRecorder, build_ffmpeg_command
from rin.config import CaptureConfig


class _FakeStdin(io.BytesIO):
    def __init__(self, parent: _FakePopen) -> None:
        super().__init__()
        self._parent = parent

    def write(self, data) -> int:  # type: ignore[override]
        self._parent.received += data
        if b"q" in data:
            self._parent._exited = True
        return len(data)

    def flush(self) -> None:
        return None


class _FakePopen:
    pids = iter(range(10_000, 99_999))

    def __init__(self, args, **_kwargs):
        self.args = args
        self.pid = next(self.pids)
        self.received = b""
        self._exited = False
        self.stdin = _FakeStdin(self)
        self.stderr = io.BytesIO(b"")
        self.returncode: int | None = None

    def wait(self, timeout=None):
        if not self._exited and timeout is not None:
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self._exited = True

    def kill(self) -> None:
        self._exited = True


def test_build_command_uses_gdigrab_offset() -> None:
    monitor = MonitorInfo(index=2, name="monitor-2", x=1920, y=0, width=2560, height=1440, is_primary=False)
    cmd = build_ffmpeg_command(
        monitor,
        Path("out.mp4"),
        capture_cfg=CaptureConfig(),
        audio_device="Microphone (Realtek)",
    )
    assert "gdigrab" in cmd
    assert "-offset_x" in cmd
    assert "1920" in cmd
    assert "-video_size" in cmd
    assert "2560x1440" in cmd
    assert any("dshow" in c for c in cmd)
    assert any("audio=Microphone (Realtek)" in c for c in cmd)
    assert "out.mp4" in cmd


def test_recorder_starts_one_process_per_monitor(tmp_path: Path) -> None:
    monitors = [
        MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=1920, height=1080, is_primary=True),
        MonitorInfo(index=2, name="monitor-2", x=1920, y=0, width=1920, height=1080, is_primary=False),
    ]
    rec = VideoRecorder(
        monitors=monitors,
        folder=tmp_path / "rec",
        capture_cfg=CaptureConfig(),
        popen_factory=_FakePopen,
    )
    rec.start()
    assert len(rec.outputs) == 2
    files = rec.stop()
    assert {p.name for p in files} == {"monitor-1.mp4", "monitor-2.mp4"}


def test_recorder_uses_devnull_for_stderr(tmp_path: Path) -> None:
    """Issue R2 (v0.3.0 review): a PIPE'd stderr would deadlock on long runs."""

    monitor = MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=800, height=600, is_primary=True)
    captured_kwargs: list[dict] = []

    def factory(args, **kwargs):
        captured_kwargs.append(kwargs)
        return _FakePopen(args, **kwargs)

    rec = VideoRecorder(
        monitors=[monitor],
        folder=tmp_path / "rec",
        capture_cfg=CaptureConfig(),
        popen_factory=factory,
    )
    rec.start()
    rec.stop()
    assert captured_kwargs[0]["stderr"] is subprocess.DEVNULL, \
        "FFmpeg stderr must be DEVNULL to avoid pipe-buffer deadlock"


def test_recorder_stop_sends_q_to_stdin(tmp_path: Path) -> None:
    monitor = MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=800, height=600, is_primary=True)
    captured: list[_FakePopen] = []

    def factory(args, **kwargs):
        proc = _FakePopen(args, **kwargs)
        captured.append(proc)
        return proc

    rec = VideoRecorder(
        monitors=[monitor],
        folder=tmp_path / "rec",
        capture_cfg=CaptureConfig(),
        popen_factory=factory,
    )
    rec.start()
    rec.stop()
    assert captured[0].received == b"q"

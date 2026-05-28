"""Benchmark recorder lifecycle overhead (target: ≤100ms with mocked ffmpeg)."""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from rin.capture.monitors import MonitorInfo
from rin.capture.recorder import VideoRecorder
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

    def __init__(self, args, **_kwargs) -> None:
        self.args = args
        self.pid = next(self.pids)
        self.received = b""
        self._exited = False
        self.stdin = _FakeStdin(self)
        self.stdout = None
        self.stderr = None
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


@pytest.mark.benchmark(group="recorder")
def test_video_recorder_start_stop_benchmark(tmp_path: Path, benchmark) -> None:
    """target: ≤100ms for start()/stop() with a mocked ffmpeg subprocess."""

    monitor = MonitorInfo(
        index=1,
        name="monitor-1",
        x=0,
        y=0,
        width=1920,
        height=1080,
        is_primary=True,
    )
    outputs: list[list[Path]] = []

    def run_cycle() -> list[Path]:
        recorder = VideoRecorder(
            monitors=[monitor],
            folder=tmp_path / "rec",
            capture_cfg=CaptureConfig(),
            popen_factory=_FakePopen,
        )
        recorder.start()
        files = recorder.stop()
        outputs[:] = [files]
        return files

    benchmark.pedantic(run_cycle, rounds=10, iterations=1, warmup_rounds=1)
    assert outputs and outputs[0][0].name == "monitor-1.mp4"

"""FFmpeg-driven video + audio recorder.

We spawn one ``ffmpeg`` subprocess per physical monitor that captures the
monitor region via Windows ``gdigrab`` and mixes in microphone + WASAPI
loopback audio via ``dshow``. Each subprocess writes its own ``monitor-N.mp4``.

Stopping is graceful: we send ``q`` to ffmpeg's stdin, which makes it
finalize the MP4 moov atom. If that fails within a small timeout we
fall back to ``terminate()``.

FFmpeg is not bundled — :func:`ffmpeg_available` is used by the UI to
warn the user when it can't be found on PATH.
"""
from __future__ import annotations

import contextlib
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import CaptureConfig
from ..utils.logging import get_logger
from .monitors import MonitorInfo

log = get_logger(__name__)


@dataclass
class RecorderProcess:
    monitor: MonitorInfo
    process: subprocess.Popen
    output: Path


def ffmpeg_available(binary: str = "ffmpeg") -> bool:
    """Return True if the ffmpeg binary is on PATH."""

    return shutil.which(binary) is not None


def build_ffmpeg_command(
    monitor: MonitorInfo,
    output: Path,
    *,
    capture_cfg: CaptureConfig,
    audio_device: str | None = None,
    binary: str = "ffmpeg",
    framerate: int = 30,
) -> list[str]:
    """Return an ffmpeg argv that records one monitor + (optional) audio device."""

    cmd: list[str] = [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "gdigrab",
        "-framerate",
        str(framerate),
        "-offset_x",
        str(monitor.x),
        "-offset_y",
        str(monitor.y),
        "-video_size",
        f"{monitor.width}x{monitor.height}",
        "-i",
        "desktop",
    ]
    if audio_device:
        cmd.extend(
            [
                "-f",
                "dshow",
                "-i",
                f"audio={audio_device}",
            ]
        )
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(framerate),
        ]
    )
    if audio_device:
        cmd.extend(
            [
                "-c:a",
                "aac",
                "-ar",
                str(capture_cfg.audio_sample_rate),
                "-ac",
                str(capture_cfg.audio_channels),
            ]
        )
    cmd.append(str(output))
    return cmd


class VideoRecorder:
    """Records every monitor in parallel via one ffmpeg subprocess per display."""

    def __init__(
        self,
        monitors: list[MonitorInfo],
        folder: Path,
        *,
        capture_cfg: CaptureConfig,
        audio_device: str | None = None,
        binary: str = "ffmpeg",
        popen_factory=None,
    ) -> None:
        self.monitors = monitors
        self.folder = folder
        self.capture_cfg = capture_cfg
        self.audio_device = audio_device
        self.binary = binary
        self._popen_factory = popen_factory or subprocess.Popen
        self._procs: list[RecorderProcess] = []
        self._started_at: datetime | None = None

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def outputs(self) -> list[Path]:
        return [p.output for p in self._procs]

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        if self._procs:
            raise RuntimeError("VideoRecorder already started")
        if not ffmpeg_available(self.binary) and self._popen_factory is subprocess.Popen:
            raise RuntimeError(f"FFmpeg binary {self.binary!r} not found on PATH")
        self.folder.mkdir(parents=True, exist_ok=True)
        self._started_at = datetime.now()
        for monitor in self.monitors:
            output = self.folder / f"monitor-{monitor.index}.mp4"
            args = build_ffmpeg_command(
                monitor,
                output,
                capture_cfg=self.capture_cfg,
                audio_device=self.audio_device,
                binary=self.binary,
            )
            proc = self._popen_factory(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                # stderr discarded (was: subprocess.PIPE). FFmpeg can emit
                # tens of KB of warnings during a long record; with a PIPE
                # that nothing drains, the ~64 KB Windows pipe buffer fills
                # and ffmpeg blocks on its next write → hung recording.
                # Diagnostic output remains available via ffmpeg's own log
                # files; we don't read or rely on stderr here.
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(RecorderProcess(monitor=monitor, process=proc, output=output))
            log.info(f"FFmpeg pid={proc.pid} recording monitor-{monitor.index} → {output}")

    def stop(self, *, timeout_seconds: float = 5.0) -> list[Path]:
        """Stop all subprocesses, returning the list of output files."""

        outputs: list[Path] = []
        for rp in self._procs:
            stdin = rp.process.stdin
            try:
                if stdin is not None and not stdin.closed:
                    stdin.write(b"q")
                    stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                # FFmpeg may have already exited (e.g. BitBlt denied under RDP,
                # DRM-protected content on screen) — its stdin pipe is closed.
                # Windows raises OSError(EINVAL) here; treat as "already stopped".
                pass
            # Explicitly close stdin so its garbage-collector finalizer doesn't
            # raise the same OSError again later from a different stack frame.
            with contextlib.suppress(BrokenPipeError, ValueError, OSError):
                if stdin is not None and not stdin.closed:
                    stdin.close()
            try:
                rp.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                log.warning(f"FFmpeg pid={rp.process.pid} did not exit gracefully, terminating")
                rp.process.terminate()
                try:
                    rp.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    rp.process.kill()
            outputs.append(rp.output)
        self._procs.clear()
        return outputs

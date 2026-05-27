"""Multi-monitor capture services.

* :func:`capture_screenshot` — fast multi-monitor PNG grab via ``mss``.
* :class:`AudioRecorder`     — mic + WASAPI loopback to a WAV file (used standalone in Phase 6 transcripts).
* :class:`VideoRecorder`     — ffmpeg subprocess pipeline for full screen + audio → MP4.
* :class:`CaptureService`    — high-level wrapper: ``take_shot()`` / ``start_recording()`` / ``stop_recording()``.

All public functions persist metadata into the SQLite database
(``captures`` + ``capture_files``) so the rest of the app can find them.
"""
from __future__ import annotations

from .audio import AudioRecorder, list_audio_devices, list_dshow_audio_devices
from .monitors import MonitorInfo, enumerate_monitors, refresh_monitor_records
from .recorder import VideoRecorder, build_ffmpeg_command, ffmpeg_available
from .screenshot import capture_screenshot
from .service import CaptureService

__all__ = [
    "AudioRecorder",
    "CaptureService",
    "MonitorInfo",
    "VideoRecorder",
    "build_ffmpeg_command",
    "capture_screenshot",
    "enumerate_monitors",
    "ffmpeg_available",
    "list_audio_devices",
    "list_dshow_audio_devices",
    "refresh_monitor_records",
]

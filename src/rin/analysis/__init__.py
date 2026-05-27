"""Analysis pipeline.

Phase 6 turns raw captures into structured ``Analysis`` rows:

* :func:`should_analyze_now`  — gate condition (outside working hours OR idle).
* :class:`Scheduler`          — APScheduler hourly job calling :func:`analyze_pending`.
* :func:`analyze_pending`     — iterate ``Capture`` rows lacking an analysis.
* :func:`analyze_capture`     — fan-out to image/video analyzer + summarizer.
"""
from __future__ import annotations

from .idle_detector import get_idle_seconds, is_idle
from .image_analyzer import analyze_image
from .keyframes import extract_keyframes, ffmpeg_available
from .ocr import extract_text, ocr_available
from .scheduler import AnalysisScheduler, should_analyze_now
from .summarizer import analyze_capture, analyze_pending, build_summary
from .transcribe import transcribe_audio, whisper_available
from .video_analyzer import analyze_video
from .working_hours import is_within_working_hours

__all__ = [
    "AnalysisScheduler",
    "analyze_capture",
    "analyze_image",
    "analyze_pending",
    "analyze_video",
    "build_summary",
    "extract_keyframes",
    "extract_text",
    "ffmpeg_available",
    "get_idle_seconds",
    "is_idle",
    "is_within_working_hours",
    "ocr_available",
    "should_analyze_now",
    "transcribe_audio",
    "whisper_available",
]

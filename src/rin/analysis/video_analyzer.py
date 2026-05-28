"""Video analyzer: keyframes + audio transcript → summary text.

Strategy:
1. Extract one frame every ``keyframe_interval_seconds`` via ffmpeg.
2. Pass each frame through :func:`analyze_image`.
3. If the source video has an audio track, hand the file to Whisper.
4. Return a structured :class:`VideoAnalysis` for the summarizer.

Heavy work (OCR, vision LLM, Whisper) is opt-in via the provided
provider / dependencies — anything missing just leaves that slot empty.
"""
from __future__ import annotations

import contextlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import AnalysisConfig
from ..llm.base import Provider
from ..utils.encryption import CaptureCipher
from ..utils.logging import get_logger
from .image_analyzer import analyze_image
from .keyframes import extract_keyframes
from .transcribe import Transcript, transcribe_audio

log = get_logger(__name__)


@contextlib.contextmanager
def _readable_video_path(video_path: Path):
    if video_path.suffix != ".enc":
        yield video_path
        return
    suffix = Path(video_path.stem).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        CaptureCipher().decrypt_file(video_path, tmp_path)
        yield tmp_path
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


@dataclass
class VideoAnalysis:
    frame_summaries: list[str] = field(default_factory=list)
    ocr_text: str = ""
    transcript: Transcript = field(default_factory=lambda: Transcript(text=""))


def analyze_video(
    video_path: Path,
    *,
    cfg: AnalysisConfig,
    provider: Provider | None = None,
    work_dir: Path | None = None,
    extract_keyframes_fn=extract_keyframes,
    transcribe_fn=transcribe_audio,
    analyze_image_fn=analyze_image,
) -> VideoAnalysis:
    """Process a single video file. Pure dependency injection for testability.

    When ``work_dir`` is None we allocate a private ``%TEMP%/rin-vid-XXXX``
    directory and **delete it before returning** so we don't leak keyframe
    PNGs across runs (issue R1 from the v0.3.0 pre-release review). If the
    caller passes their own ``work_dir`` we leave it alone — that's their
    responsibility.
    """

    if not video_path.exists():
        return VideoAnalysis()

    with _readable_video_path(video_path) as readable_video_path:
        caller_provided_dir = work_dir is not None
        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="rin-vid-"))
        work_dir.mkdir(parents=True, exist_ok=True)
        keyframes_dir = work_dir / "keyframes"

        try:
            frames = extract_keyframes_fn(
                readable_video_path,
                keyframes_dir,
                interval_seconds=cfg.keyframe_interval_seconds,
            )
            summaries: list[str] = []
            ocr_chunks: list[str] = []
            for frame in frames:
                analysis = analyze_image_fn(frame, provider=provider)
                if analysis.summary:
                    summaries.append(analysis.summary)
                if analysis.text:
                    ocr_chunks.append(analysis.text)

            transcript = transcribe_fn(readable_video_path, model_name=cfg.whisper_model)

            return VideoAnalysis(
                frame_summaries=summaries,
                ocr_text="\n\n".join(ocr_chunks),
                transcript=transcript,
            )
        finally:
            if not caller_provided_dir:
                shutil.rmtree(work_dir, ignore_errors=True)

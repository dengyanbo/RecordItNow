"""Audio transcription via ``faster-whisper``.

Like the OCR module, the model is loaded lazily and cached. The chosen
model name is read from :class:`~rin.config.AnalysisConfig`.

We use the CPU backend by default; PyTorch / GPU is not required.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import models_cache_dir
from ..utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Transcript:
    text: str
    language: str | None = None
    segments: list[dict] = field(default_factory=list)


_models: dict[str, object] = {}
_model_lock = threading.Lock()


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model(model_name: str):
    if model_name in _models:
        return _models[model_name]
    with _model_lock:
        if model_name in _models:
            return _models[model_name]
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.warning("faster-whisper not installed; transcription disabled")
            return None
        log.info(f"Loading Whisper model {model_name!r} (CPU, int8)…")
        download_root = models_cache_dir() / "whisper"
        download_root.mkdir(parents=True, exist_ok=True)
        _models[model_name] = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(download_root),
        )
        return _models[model_name]


def transcribe_audio(audio_path: Path, *, model_name: str = "small") -> Transcript:
    """Transcribe an audio file. Returns an empty transcript on failure."""

    if not audio_path.exists():
        return Transcript(text="")
    model = _get_model(model_name)
    if model is None:
        return Transcript(text="")
    try:
        segments_iter, info = model.transcribe(str(audio_path), beam_size=1)
        segments = []
        text_parts = []
        for seg in segments_iter:
            segments.append({"start": seg.start, "end": seg.end, "text": seg.text})
            text_parts.append(seg.text)
        return Transcript(
            text="".join(text_parts).strip(),
            language=info.language if hasattr(info, "language") else None,
            segments=segments,
        )
    except Exception as exc:
        log.warning(f"Transcription failed for {audio_path}: {exc}")
        return Transcript(text="")


def reset_models() -> None:
    """Drop cached models. Tests use this between runs."""

    _models.clear()

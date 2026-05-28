"""OCR wrapper around ``rapidocr-onnxruntime``.

The OCR model is heavy and slow to import; we lazy-load and cache it.
Missing optional deps degrade to "no OCR available" rather than failing
the analysis run.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..utils.logging import get_logger

log = get_logger(__name__)

_engine = None
_engine_lock = threading.Lock()


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            log.warning("rapidocr-onnxruntime not installed; OCR disabled")
            return None
        _engine = RapidOCR()
        log.info("RapidOCR engine initialized")
        return _engine


def _configured_languages() -> list[str]:
    try:
        from ..config import RinConfig

        return list(RinConfig.load().analysis.ocr_languages)
    except Exception:
        return ["en", "ch_sim"]



def extract_text(image_path: Path, *, languages: list[str] | None = None) -> str:
    """Return whitespace-joined OCR text for ``image_path`` (empty on failure)."""

    engine = _get_engine()
    if engine is None:
        return ""
    active_languages = list(languages or _configured_languages())
    try:
        try:
            result, _elapsed = engine(str(image_path), languages=active_languages)
        except TypeError:
            result, _elapsed = engine(str(image_path))
    except Exception as exc:
        log.warning(f"OCR failed for {image_path}: {exc}")
        return ""
    if not result:
        return ""
    lines = [item[1] for item in result if len(item) > 1 and isinstance(item[1], str)]
    return "\n".join(lines).strip()


def reset_engine() -> None:
    """Drop the cached engine. Tests use this to swap mocks in/out."""

    global _engine
    _engine = None

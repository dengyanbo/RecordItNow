"""Per-screenshot analyzer.

Combines local OCR with the optional vision-capable LLM to produce a
single :class:`~rin.llm.base.ImageAnalysis`. Both layers are
independently optional:

* OCR missing → ``text`` is empty.
* LLM missing or vision-incapable → ``summary`` is a stub derived from OCR.
"""
from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

from ..llm.base import ImageAnalysis, LLMError, Provider
from ..utils.encryption import CaptureCipher
from ..utils.logging import get_logger
from .ocr import extract_text

log = get_logger(__name__)


@contextlib.contextmanager
def _readable_image_path(image_path: Path):
    if image_path.suffix != ".enc":
        yield image_path
        return
    suffix = Path(image_path.stem).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        CaptureCipher().decrypt_file(image_path, tmp_path)
        yield tmp_path
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


def analyze_image(image_path: Path, *, provider: Provider | None = None) -> ImageAnalysis:
    with _readable_image_path(image_path) as readable_image_path:
        ocr_text = extract_text(readable_image_path)
        summary = ""
        if provider is not None and provider.capabilities.supports_vision:
            try:
                llm_result = provider.analyze_image(readable_image_path)
                summary = llm_result.summary
                if not ocr_text and llm_result.text:
                    ocr_text = llm_result.text
            except LLMError as exc:
                log.warning(f"LLM image analysis failed for {image_path}: {exc}")
    if not summary:
        summary = _fallback_summary(ocr_text)
    return ImageAnalysis(summary=summary, text=ocr_text)


def _fallback_summary(ocr_text: str) -> str:
    if not ocr_text:
        return "Screenshot captured. No OCR text and no LLM summary available."
    lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    snippet = " ".join(lines[:6])
    return f"Screenshot captured. OCR excerpt: {snippet[:280]}"

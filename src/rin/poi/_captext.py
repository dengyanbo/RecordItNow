"""Shared single-capture text loader for the PoI helpers.

Both :mod:`rin.poi.from_capture` and :mod:`rin.poi.diagnostic` need the
same "load a capture's analyses + transcripts and concatenate the signal
text" query. Keeping it in one place avoids the two copies drifting apart.
"""
from __future__ import annotations

from sqlalchemy import select

from ..storage import session
from ..storage.models import Analysis, Capture, Transcript


def load_capture_text(capture_id: int) -> tuple[str, str] | None:
    """Return ``(combined_text, summary)`` for a capture, or ``None`` if it
    doesn't exist.

    * ``summary`` — every analysis ``summary`` joined by newlines.
    * ``combined_text`` — all summaries + OCR text + transcript text joined;
      this is the full signal a PoI matcher runs against.

    For a capture that exists but has no analyses/transcripts, both strings
    are empty (``("", "")``) — distinct from the missing-capture ``None``.
    """

    with session() as s:
        if s.get(Capture, capture_id) is None:
            return None
        analyses = list(
            s.scalars(
                select(Analysis)
                .where(Analysis.capture_id == capture_id)
                .order_by(Analysis.created_at)
            )
        )
        transcripts = list(
            s.scalars(
                select(Transcript)
                .where(Transcript.capture_id == capture_id)
                .order_by(Transcript.created_at)
            )
        )

    summary_parts = [a.summary for a in analyses if a.summary]
    ocr_parts = [a.ocr_text for a in analyses if a.ocr_text]
    transcript_parts = [t.text for t in transcripts if t.text]
    summary = "\n".join(summary_parts).strip()
    combined = "\n".join(summary_parts + ocr_parts + transcript_parts).strip()
    return combined, summary

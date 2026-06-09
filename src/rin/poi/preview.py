"""Phase 2-A (v0.14.0): live regex/keyword preview for the PoI editor.

Runs in a Qt worker thread (300 ms debounce in the UI). Returns a count
of captures that match + a few example snippets so the user can spot-
check whether their regex is "too broad" (matches 500) or "too narrow"
(matches 0).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from ..storage import session
from ..storage.models import Analysis, Capture, Transcript
from ..utils.logging import get_logger
from .discovery import (
    EVIDENCE_QUOTE_CONTEXT,
    EVIDENCE_QUOTE_MAX_LEN,
    extract_evidence_quote,
)

log = get_logger(__name__)

#: Maximum captures the preview scans per call. Bounded to keep the UI
#: snappy even on a year-old DB.
PREVIEW_SAMPLE_LIMIT = 200
#: Default look-back window in days.
PREVIEW_DEFAULT_DAYS = 7
#: Default number of example snippets surfaced to the user.
PREVIEW_DEFAULT_EXAMPLES = 3


@dataclass(slots=True, frozen=True)
class PreviewExample:
    capture_id: int
    matched_term: str
    snippet: str


@dataclass(slots=True, frozen=True)
class PreviewResult:
    matched_count: int
    examples: list[PreviewExample]
    sampled_captures: int
    error: str | None = None


def preview_matches(
    *,
    regex_patterns: list[str] | None = None,
    keywords: list[str] | None = None,
    days: int = PREVIEW_DEFAULT_DAYS,
    max_examples: int = PREVIEW_DEFAULT_EXAMPLES,
    sample_limit: int = PREVIEW_SAMPLE_LIMIT,
    now: datetime | None = None,
    rng_seed: int = 1234,
) -> PreviewResult:
    """Match user-entered regex + keywords against recent captures.

    - Compiles each regex with ``re.IGNORECASE``. The first invalid regex
      short-circuits with ``error`` set so the UI can surface it.
    - Keywords are case-insensitive literal substring matches.
    - Captures with no analysis text and no transcript are skipped.
    - Returns up to ``max_examples`` distinct capture snippets selected
      deterministically (seeded RNG).
    """

    patterns: list[re.Pattern[str]] = []
    for raw in regex_patterns or []:
        pattern = raw.strip()
        if not pattern:
            continue
        try:
            patterns.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            return PreviewResult(
                matched_count=0,
                examples=[],
                sampled_captures=0,
                error=f"Invalid regex {pattern!r}: {exc}",
            )

    keyword_terms: list[str] = []
    for raw in keywords or []:
        term = raw.strip()
        if term:
            keyword_terms.append(term)

    if not patterns and not keyword_terms:
        return PreviewResult(matched_count=0, examples=[], sampled_captures=0)

    records = _load_recent_records(
        now=now or datetime.now(),
        days=max(0, int(days)),
        sample_limit=max(1, int(sample_limit)),
    )
    if not records:
        return PreviewResult(matched_count=0, examples=[], sampled_captures=0)

    examples: list[PreviewExample] = []
    matched_ids: set[int] = set()
    for capture_id, text in records:
        if not text:
            continue
        match_term, span = _first_match(patterns, keyword_terms, text)
        if match_term is None or span is None:
            continue
        matched_ids.add(capture_id)
        snippet = extract_evidence_quote(
            text,
            span[0],
            span[1],
            context=EVIDENCE_QUOTE_CONTEXT,
            max_len=EVIDENCE_QUOTE_MAX_LEN,
        )
        if snippet:
            examples.append(
                PreviewExample(
                    capture_id=capture_id,
                    matched_term=match_term,
                    snippet=snippet,
                )
            )

    if max_examples > 0 and len(examples) > max_examples:
        rng = random.Random(rng_seed)
        examples = rng.sample(examples, max_examples)
    elif max_examples == 0:
        examples = []

    return PreviewResult(
        matched_count=len(matched_ids),
        examples=examples,
        sampled_captures=len(records),
    )


def _first_match(
    patterns: list[re.Pattern[str]],
    keyword_terms: list[str],
    text: str,
) -> tuple[str | None, tuple[int, int] | None]:
    for pattern in patterns:
        match = pattern.search(text)
        if match is not None:
            return match.group(0), (match.start(), match.end())
    if not keyword_terms:
        return None, None
    lower = text.casefold()
    for term in keyword_terms:
        needle = term.casefold()
        if not needle:
            continue
        idx = lower.find(needle)
        if idx >= 0:
            return term, (idx, idx + len(needle))
    return None, None


def _load_recent_records(
    *, now: datetime, days: int, sample_limit: int
) -> list[tuple[int, str]]:
    cutoff = now - timedelta(days=days)
    with session() as s:
        captures = list(
            s.scalars(
                select(Capture)
                .where(Capture.started_at >= cutoff)
                .order_by(Capture.started_at.desc())
                .limit(sample_limit)
            )
        )
        if not captures:
            return []
        capture_ids = [capture.id for capture in captures]
        analyses = list(
            s.scalars(
                select(Analysis).where(Analysis.capture_id.in_(capture_ids))
            )
        )
        transcripts = list(
            s.scalars(
                select(Transcript).where(Transcript.capture_id.in_(capture_ids))
            )
        )

    parts_by_capture: dict[int, list[str]] = {cid: [] for cid in capture_ids}
    for analysis in analyses:
        bucket = parts_by_capture[analysis.capture_id]
        if analysis.summary:
            bucket.append(analysis.summary)
        if analysis.ocr_text:
            bucket.append(analysis.ocr_text)
    for transcript in transcripts:
        if transcript.text:
            parts_by_capture[transcript.capture_id].append(transcript.text)

    return [
        (cid, "\n".join(parts).strip())
        for cid, parts in parts_by_capture.items()
    ]


__all__ = [
    "PreviewExample",
    "PreviewResult",
    "preview_matches",
]

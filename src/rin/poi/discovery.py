"""On-demand Point-of-Interest discovery over recent captures."""
from __future__ import annotations

import json
import math
import random
import re
import string
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select

from ..config import RinConfig
from ..llm.base import Provider
from ..storage import session
from ..storage.models import Analysis, Capture, PoICandidate, Transcript
from ..utils.logging import get_logger

log = get_logger(__name__)

_REGEX_PATTERNS = (
    r"\bINC\d{7}\b",
    r"\bREQ\d{7}\b",
    r"\bSR\d{7,10}\b",
    r"\bCASE\d{6,8}\b",
    r"#\d{4,6}\b",
    r"\bJIRA-\d+\b",
    r"\bGH-\d+\b",
    r"#\d{3,6}\b",
)
_DOMAIN_RE = re.compile(r"https?://([^\s/]+)/?", re.IGNORECASE)
_PHRASE_SPLIT_RE = re.compile(rf"[\s{re.escape(string.punctuation)}]+")
_PHRASE_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]+( [A-Z][A-Za-z0-9]+)+$")
_NAMEISH_WORD_RE = re.compile(r"^(?:[A-Z][A-Za-z0-9]*|[A-Z0-9]{2,})$")
_KIND_ORDER = {"regex": 0, "domain": 1, "phrase": 2, "llm": 3}

#: Phase 2-A (v0.14.0): ±60-char window around a match used as
#: ``PoICandidate.evidence_quote``.
EVIDENCE_QUOTE_CONTEXT = 60
EVIDENCE_QUOTE_MAX_LEN = 200


def extract_evidence_quote(
    text: str,
    span_start: int,
    span_end: int,
    *,
    context: int = EVIDENCE_QUOTE_CONTEXT,
    max_len: int = EVIDENCE_QUOTE_MAX_LEN,
) -> str:
    """Return a short snippet of ``text`` around the match span.

    - Pads with ``…`` when truncating the start/end.
    - Collapses internal whitespace + newlines to single spaces.
    - Hard-caps the rendered length at ``max_len`` so a giant match
      can't blow up the persisted value.
    """

    if not text or span_end <= span_start:
        return ""
    span_start = max(0, span_start)
    span_end = min(len(text), span_end)
    start = max(0, span_start - context)
    end = min(len(text), span_end + context)
    snippet = text[start:end]
    snippet = " ".join(snippet.split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    snippet = f"{prefix}{snippet}{suffix}"
    if len(snippet) > max_len:
        snippet = snippet[: max_len - 1].rstrip() + "…"
    return snippet


@dataclass(slots=True)
class PoICandidateDraft:
    """In-memory candidate before persistence."""

    suggested_name: str
    kind: Literal["regex", "domain", "phrase", "llm"]
    description: str | None
    evidence_capture_ids: list[int]
    score: float
    # Phase 2-A (v0.14.0): short snippet (±60 chars) around the first
    # occurrence of the match in a real capture. ``None`` when discovery
    # can't pin a specific span (e.g. older code paths or LLM-mined
    # candidates whose name doesn't literally appear in the summary).
    evidence_quote: str | None = None


@dataclass(slots=True)
class _CaptureRecord:
    capture_id: int
    started_at: datetime
    summary: str
    ocr_text: str
    transcript_text: str

    @property
    def combined_text(self) -> str:
        return "\n".join(
            part for part in (self.summary, self.ocr_text, self.transcript_text) if part
        )


def discover(
    cfg: RinConfig,
    *,
    days: int = 14,
    use_llm: bool = False,
    provider: Provider | None = None,
    now: datetime | None = None,
    min_evidence: int = 2,
    max_candidates: int = 30,
) -> list[PoICandidateDraft]:
    """Mine captures from the last `days` days for PoI candidates.

    Strategies (in order):
      1. Regex mining (strong signal: ticket IDs, JIRA cards, GH refs).
      2. Domain mining (frequent URLs / hostnames in OCR text).
      3. Phrase mining (top noun-phrase-ish tokens via stdlib TF-IDF-lite).
      4. LLM batch (opt-in via use_llm=True) — single call with sampled
         capture summaries, asks LLM to extract recurring entities.

    Returns candidates sorted by score descending, capped at
    `max_candidates`. Filters out anything that already matches an
    enabled `topic` spec (so we don't re-suggest existing PoIs).
    """

    if max_candidates <= 0:
        return []

    min_evidence = max(1, int(min_evidence))
    window_now = now or datetime.now()
    records = _load_recent_capture_records(now=window_now, days=max(0, int(days)))
    if not records:
        return []

    strategies = [
        ("regex", lambda: _mine_regex(records, min_evidence=min_evidence)),
        ("domain", lambda: _mine_domains(records, min_evidence=min_evidence)),
        ("phrase", lambda: _mine_phrases(records, min_evidence=min_evidence)),
        (
            "llm",
            lambda: _mine_llm(
                records,
                use_llm=use_llm,
                provider=provider,
                min_evidence=min_evidence,
            ),
        ),
    ]

    discovered: list[PoICandidateDraft] = []
    for name, strategy in strategies:
        try:
            discovered.extend(strategy())
        except Exception as exc:  # pragma: no cover - defensive logging path
            log.warning(f"poi discovery: {name} strategy failed ({exc})")

    if not discovered:
        return []

    exact_terms, keyword_terms = _existing_topic_terms(cfg)
    candidates = [
        draft
        for draft in _merge_candidates(discovered)
        if not _matches_existing_topic(draft.suggested_name, exact_terms, keyword_terms)
    ]
    candidates.sort(key=_candidate_sort_key)
    return candidates[:max_candidates]


def persist_candidates(
    drafts: list[PoICandidateDraft],
    *,
    dedupe_against_existing: bool = True,
) -> list[int]:
    """Insert drafts as `poi_candidates` rows (status=pending,
    decided_by='auto'). Returns inserted ids.

    If `dedupe_against_existing` (default True), skip a draft if a
    pending OR accepted candidate already exists with the same
    suggested_name (case-insensitive)."""

    normalized: list[PoICandidateDraft] = []
    for draft in drafts:
        name = _normalize_text(draft.suggested_name)
        if not name:
            continue
        normalized.append(
            PoICandidateDraft(
                suggested_name=name,
                kind=draft.kind,
                description=_normalize_text(draft.description) or None,
                evidence_capture_ids=_unique_capture_ids(draft.evidence_capture_ids),
                score=float(draft.score),
                evidence_quote=draft.evidence_quote,
            )
        )
    if not normalized:
        return []

    inserted_ids: list[int] = []
    with session() as s:
        known_names: set[str] = set()
        if dedupe_against_existing:
            rows = s.scalars(
                select(PoICandidate).where(
                    PoICandidate.status.in_(["pending", "accepted"])
                )
            ).all()
            known_names.update(row.suggested_name.casefold() for row in rows)

        batch_names = set(known_names)
        for draft in normalized:
            key = draft.suggested_name.casefold()
            if key in batch_names:
                continue
            row = PoICandidate(
                suggested_name=draft.suggested_name,
                kind=draft.kind,
                description=draft.description,
                evidence_capture_ids=json.dumps(draft.evidence_capture_ids),
                evidence_quote=draft.evidence_quote,
                score=draft.score,
                status="pending",
                decided_by="auto",
            )
            s.add(row)
            s.flush()
            inserted_ids.append(row.id)
            batch_names.add(key)
    return inserted_ids


def _load_recent_capture_records(*, now: datetime, days: int) -> list[_CaptureRecord]:
    cutoff = now - timedelta(days=days)
    with session() as s:
        captures = list(
            s.scalars(
                select(Capture)
                .where(Capture.started_at >= cutoff)
                .order_by(Capture.started_at.desc())
            )
        )
        if not captures:
            return []

        capture_ids = [capture.id for capture in captures]
        analyses = list(
            s.scalars(
                select(Analysis)
                .where(Analysis.capture_id.in_(capture_ids))
                .order_by(Analysis.capture_id, Analysis.created_at)
            )
        )
        transcripts = list(
            s.scalars(
                select(Transcript)
                .where(Transcript.capture_id.in_(capture_ids))
                .order_by(Transcript.capture_id, Transcript.created_at)
            )
        )

    analyses_by_capture: dict[int, list[Analysis]] = defaultdict(list)
    for analysis in analyses:
        analyses_by_capture[analysis.capture_id].append(analysis)

    transcripts_by_capture: dict[int, list[Transcript]] = defaultdict(list)
    for transcript in transcripts:
        transcripts_by_capture[transcript.capture_id].append(transcript)

    records: list[_CaptureRecord] = []
    for capture in captures:
        analysis_rows = analyses_by_capture.get(capture.id, [])
        transcript_rows = transcripts_by_capture.get(capture.id, [])
        records.append(
            _CaptureRecord(
                capture_id=capture.id,
                started_at=capture.started_at,
                summary=_join_unique_text(row.summary for row in analysis_rows),
                ocr_text=_join_unique_text(row.ocr_text for row in analysis_rows),
                transcript_text=_join_unique_text(row.text for row in transcript_rows),
            )
        )
    return records


def _mine_regex(
    records: list[_CaptureRecord], *, min_evidence: int
) -> list[PoICandidateDraft]:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in _REGEX_PATTERNS]
    hits: dict[str, set[int]] = defaultdict(set)
    quotes: dict[str, str] = {}

    for record in records:
        text = record.combined_text
        if not text:
            continue
        matches_in_capture: set[str] = set()
        for pattern in compiled:
            for match in pattern.finditer(text):
                token = _normalize_text(match.group(0)).upper()
                if not token:
                    continue
                matches_in_capture.add(token)
                if token not in quotes:
                    quote = extract_evidence_quote(text, match.start(), match.end())
                    if quote:
                        quotes[token] = quote
        for token in matches_in_capture:
            hits[token].add(record.capture_id)

    drafts: list[PoICandidateDraft] = []
    for token, capture_ids in hits.items():
        evidence_ids = sorted(capture_ids)
        count = len(evidence_ids)
        if count < min_evidence:
            continue
        drafts.append(
            PoICandidateDraft(
                suggested_name=token,
                kind="regex",
                description=f"Recurring ID pattern '{token}' seen in {count} captures.",
                evidence_capture_ids=evidence_ids,
                score=float(count),
                evidence_quote=quotes.get(token),
            )
        )
    drafts.sort(key=_candidate_sort_key)
    return drafts


def _mine_domains(
    records: list[_CaptureRecord], *, min_evidence: int
) -> list[PoICandidateDraft]:
    hits: dict[str, set[int]] = defaultdict(set)
    quotes: dict[str, str] = {}

    for record in records:
        if not record.ocr_text:
            continue
        domains_in_capture: set[str] = set()
        for match in _DOMAIN_RE.finditer(record.ocr_text):
            host = match.group(1)
            domain = host.strip().lower().rstrip(".,;:!?)\"']}")
            domain = domain.removeprefix("www.")
            domain = domain.split(":", 1)[0]
            if not domain:
                continue
            if domain in {"localhost", "127.0.0.1"}:
                continue
            if domain.endswith(".local"):
                continue
            domains_in_capture.add(domain)
            if domain not in quotes:
                quote = extract_evidence_quote(
                    record.ocr_text, match.start(), match.end()
                )
                if quote:
                    quotes[domain] = quote
        for domain in domains_in_capture:
            hits[domain].add(record.capture_id)

    drafts: list[PoICandidateDraft] = []
    for domain, capture_ids in hits.items():
        evidence_ids = sorted(capture_ids)
        count = len(evidence_ids)
        if count < min_evidence:
            continue
        drafts.append(
            PoICandidateDraft(
                suggested_name=domain,
                kind="domain",
                description=f"Domain seen in {count} captures.",
                evidence_capture_ids=evidence_ids,
                score=float(math.log2(count)),
                evidence_quote=quotes.get(domain),
            )
        )
    drafts.sort(key=_candidate_sort_key)
    return drafts[:10]


def _mine_phrases(
    records: list[_CaptureRecord], *, min_evidence: int
) -> list[PoICandidateDraft]:
    hits: dict[str, set[int]] = defaultdict(set)
    quotes: dict[str, str] = {}

    for record in records:
        if not record.summary:
            continue
        tokens = [token for token in _PHRASE_SPLIT_RE.split(record.summary) if token]
        if len(tokens) < 2:
            continue
        phrases_in_capture: set[str] = set()
        for width in (2, 3):
            for start in range(len(tokens) - width + 1):
                words = tokens[start : start + width]
                if not _mostly_title_or_upper(words):
                    continue
                phrase = " ".join(words)
                if not _PHRASE_NAME_RE.fullmatch(phrase):
                    continue
                phrases_in_capture.add(phrase)
        for phrase in phrases_in_capture:
            hits[phrase].add(record.capture_id)
            if phrase not in quotes:
                idx = record.summary.find(phrase)
                if idx >= 0:
                    quote = extract_evidence_quote(
                        record.summary, idx, idx + len(phrase)
                    )
                    if quote:
                        quotes[phrase] = quote

    drafts: list[PoICandidateDraft] = []
    for phrase, capture_ids in hits.items():
        evidence_ids = sorted(capture_ids)
        count = len(evidence_ids)
        if count < min_evidence:
            continue
        drafts.append(
            PoICandidateDraft(
                suggested_name=phrase,
                kind="phrase",
                description=f"Recurring phrase '{phrase}' in {count} captures.",
                evidence_capture_ids=evidence_ids,
                score=float(count),
                evidence_quote=quotes.get(phrase),
            )
        )
    drafts.sort(key=_candidate_sort_key)
    return drafts[:10]


def _mine_llm(
    records: list[_CaptureRecord],
    *,
    use_llm: bool,
    provider: Provider | None,
    min_evidence: int,
) -> list[PoICandidateDraft]:
    if not use_llm or provider is None:
        return []

    summaries = [(record.capture_id, record.summary) for record in records if record.summary]
    if not summaries:
        return []

    rng = random.Random(42)
    sample_size = min(20, len(summaries))
    sampled = summaries if sample_size == len(summaries) else rng.sample(summaries, sample_size)
    joined_summaries = "\n".join(
        f"cap-{capture_id}: {_normalize_text(summary)}"
        for capture_id, summary in sampled
    )
    prompt = (
        "Below are summaries of a user's screen activity. List up to 10 recurring "
        "topics or named entities (projects, customers, products, papers, people) "
        "that appear across multiple summaries. Output one per line as JSON: "
        '{"name": "...", "description": "one-line"}. No prose, no markdown fences.\n\n'
        + joined_summaries
    )
    response = provider.analyze_text(prompt)

    drafts: list[PoICandidateDraft] = []
    seen_names: set[str] = set()
    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if not isinstance(name, str):
            continue
        name = _normalize_text(name)
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        evidence_ids = []
        evidence_quote: str | None = None
        for record in records:
            haystack = record.combined_text
            if not haystack:
                continue
            lower = haystack.casefold()
            idx = lower.find(key)
            if idx < 0:
                continue
            evidence_ids.append(record.capture_id)
            if evidence_quote is None:
                quote = extract_evidence_quote(
                    haystack, idx, idx + len(key)
                )
                if quote:
                    evidence_quote = quote
        evidence_ids = _unique_capture_ids(evidence_ids)
        if len(evidence_ids) < min_evidence:
            continue
        description = payload.get("description")
        if not isinstance(description, str):
            description = None
        drafts.append(
            PoICandidateDraft(
                suggested_name=name,
                kind="llm",
                description=_normalize_text(description) or None,
                evidence_capture_ids=evidence_ids,
                score=0.5,
                evidence_quote=evidence_quote,
            )
        )
        seen_names.add(key)
    drafts.sort(key=_candidate_sort_key)
    return drafts


def _existing_topic_terms(cfg: RinConfig) -> tuple[set[str], list[str]]:
    section = cfg.skills.config_for_skill("topic")
    if not isinstance(section, dict):
        return set(), []

    topics = section.get("topics")
    if not isinstance(topics, list):
        return set(), []

    exact_terms: set[str] = set()
    keyword_terms: list[str] = []
    for topic in topics:
        if isinstance(topic, str):
            normalized = _normalize_text(topic).casefold()
            if normalized:
                exact_terms.add(normalized)
                keyword_terms.append(normalized)
            continue
        if not isinstance(topic, dict):
            continue

        name = topic.get("name")
        if isinstance(name, str):
            normalized = _normalize_text(name).casefold()
            if normalized:
                exact_terms.add(normalized)

        for key in ("aliases", "keywords"):
            values = topic.get(key)
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                normalized = _normalize_text(value).casefold()
                if not normalized:
                    continue
                exact_terms.add(normalized)
                keyword_terms.append(normalized)

    return exact_terms, keyword_terms


def _matches_existing_topic(
    suggested_name: str,
    exact_terms: set[str],
    keyword_terms: list[str],
) -> bool:
    normalized = _normalize_text(suggested_name).casefold()
    if not normalized:
        return True
    if normalized in exact_terms:
        return True
    return any(keyword in normalized for keyword in keyword_terms)


def _merge_candidates(candidates: list[PoICandidateDraft]) -> list[PoICandidateDraft]:
    merged: dict[str, PoICandidateDraft] = {}
    for draft in candidates:
        name = _normalize_text(draft.suggested_name)
        if not name:
            continue
        key = name.casefold()
        evidence_ids = _unique_capture_ids(draft.evidence_capture_ids)
        candidate = PoICandidateDraft(
            suggested_name=name,
            kind=draft.kind,
            description=_normalize_text(draft.description) or None,
            evidence_capture_ids=evidence_ids,
            score=float(draft.score),
            evidence_quote=draft.evidence_quote,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue

        combined_evidence = _unique_capture_ids(
            existing.evidence_capture_ids + candidate.evidence_capture_ids
        )
        # Prefer the candidate.evidence_quote of the stronger draft, but
        # fall back to whichever quote is non-empty so we never lose it.
        if candidate.score > existing.score:
            merged[key] = PoICandidateDraft(
                suggested_name=candidate.suggested_name,
                kind=candidate.kind,
                description=candidate.description or existing.description,
                evidence_capture_ids=combined_evidence,
                score=candidate.score,
                evidence_quote=candidate.evidence_quote or existing.evidence_quote,
            )
            continue

        merged[key] = PoICandidateDraft(
            suggested_name=existing.suggested_name,
            kind=existing.kind,
            description=existing.description or candidate.description,
            evidence_capture_ids=combined_evidence,
            score=existing.score,
            evidence_quote=existing.evidence_quote or candidate.evidence_quote,
        )
    return list(merged.values())


def _join_unique_text(parts) -> str:
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        normalized = _normalize_text(part)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return "\n".join(cleaned)


def _unique_capture_ids(capture_ids: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for capture_id in capture_ids:
        if capture_id in seen:
            continue
        seen.add(capture_id)
        ordered.append(capture_id)
    return ordered


def _mostly_title_or_upper(words: list[str]) -> bool:
    matches = sum(1 for word in words if _NAMEISH_WORD_RE.fullmatch(word))
    return matches >= max(2, len(words) - 1)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _candidate_sort_key(draft: PoICandidateDraft) -> tuple[float, int, int, str]:
    return (
        -draft.score,
        -len(draft.evidence_capture_ids),
        _KIND_ORDER.get(draft.kind, 99),
        draft.suggested_name.casefold(),
    )

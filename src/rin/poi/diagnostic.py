"""Phase 2-C (v0.16.0): "Why didn't this match?" diagnostic.

Given a :class:`TopicSpec` and a capture ID, run each layer of the
matching pipeline (regex, keywords, aliases, optional LLM judge) and
report ``pass / fail`` per step with the matched substring (on pass)
or the closest substring (on fail). Lets users iterate on a PoI by
seeing exactly which step their text fails on.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Literal

from ..llm.base import LLMError, Provider
from ..skills.builtin.topic.skill import TopicSpec
from ._captext import load_capture_text

StepKind = Literal["regex", "keyword", "alias", "llm_judge"]

_PREVIEW_RADIUS = 60


@dataclass(slots=True, frozen=True)
class DiagnosticStep:
    """One row in the diagnostic readout."""

    kind: StepKind
    value: str           # the pattern / keyword / "—" for llm_judge
    passed: bool
    matched_text: str | None = None  # substring around the hit (on pass)
    closest_text: str | None = None  # best fuzzy match (on miss)
    notes: str = ""


@dataclass(slots=True, frozen=True)
class DiagnosticResult:
    """Full diagnostic readout for one (topic, capture) pair."""

    topic_name: str
    capture_id: int
    overall_match: bool
    steps: list[DiagnosticStep] = field(default_factory=list)
    capture_text_chars: int = 0
    summary_preview: str = ""


def diagnose_topic_against_capture(
    topic: TopicSpec,
    capture_id: int,
    *,
    provider: Provider | None = None,
) -> DiagnosticResult | None:
    """Run every matching layer in order and report a per-step result.

    Returns ``None`` when the capture row does not exist. ``provider``
    is only used when the topic has ``llm_judge=True``; otherwise the
    LLM step records "skipped".
    """

    bundle = load_capture_text(capture_id)
    if bundle is None:
        return None
    text, summary = bundle

    steps: list[DiagnosticStep] = []

    # Regex tier
    if topic.regex:
        for pattern in topic.regex:
            steps.append(_regex_step(pattern, text))
    else:
        steps.append(
            DiagnosticStep(
                kind="regex",
                value="(no patterns configured)",
                passed=False,
                notes="No regex patterns on this PoI — skipped.",
            )
        )

    # Keyword tier
    if topic.keywords:
        for keyword in topic.keywords:
            steps.append(_substring_step("keyword", keyword, text))
    else:
        steps.append(
            DiagnosticStep(
                kind="keyword",
                value="(no keywords configured)",
                passed=False,
                notes="No keywords on this PoI — skipped.",
            )
        )

    # Alias tier
    if topic.aliases:
        for alias in topic.aliases:
            steps.append(_substring_step("alias", alias, text))

    # LLM judge tier
    if topic.llm_judge:
        steps.append(_llm_step(topic, text, provider))

    overall = any(
        step.passed
        for step in steps
        if step.kind in ("regex", "keyword", "alias", "llm_judge")
    )

    summary_lines = (summary or "").strip().splitlines()
    summary_preview = summary_lines[0][:140] if summary_lines else ""

    return DiagnosticResult(
        topic_name=topic.name,
        capture_id=capture_id,
        overall_match=overall,
        steps=steps,
        capture_text_chars=len(text),
        summary_preview=summary_preview,
    )


def _regex_step(pattern: str, text: str) -> DiagnosticStep:
    if not text:
        return DiagnosticStep(
            kind="regex",
            value=pattern,
            passed=False,
            notes="Capture has no text to scan.",
        )
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return DiagnosticStep(
            kind="regex",
            value=pattern,
            passed=False,
            notes=f"Invalid regex: {exc}",
        )
    match = compiled.search(text)
    if match is not None:
        return DiagnosticStep(
            kind="regex",
            value=pattern,
            passed=True,
            matched_text=_window(text, match.start(), match.end()),
        )
    return DiagnosticStep(
        kind="regex",
        value=pattern,
        passed=False,
        notes="Pattern did not match.",
    )


def _substring_step(kind: StepKind, term: str, text: str) -> DiagnosticStep:
    needle = term.strip()
    if not needle:
        return DiagnosticStep(
            kind=kind, value=term, passed=False, notes="Empty term."
        )
    lowered_text = text.lower()
    lowered_needle = needle.lower()
    idx = lowered_text.find(lowered_needle)
    if idx >= 0:
        end = idx + len(needle)
        return DiagnosticStep(
            kind=kind,
            value=term,
            passed=True,
            matched_text=_window(text, idx, end),
        )
    closest = _closest_substring(text, needle)
    return DiagnosticStep(
        kind=kind,
        value=term,
        passed=False,
        closest_text=closest,
        notes="Not found." if closest is None else "Not found; closest match shown.",
    )


def _llm_step(
    topic: TopicSpec,
    text: str,
    provider: Provider | None,
) -> DiagnosticStep:
    if provider is None:
        return DiagnosticStep(
            kind="llm_judge",
            value="(YES/NO classifier)",
            passed=False,
            notes="No provider configured; LLM judge skipped.",
        )
    if not text:
        return DiagnosticStep(
            kind="llm_judge",
            value="(YES/NO classifier)",
            passed=False,
            notes="Capture has no text.",
        )
    snippet = text[:2000]
    prompt = (
        f"Is the following capture about '{topic.name}'? "
        f"Description: {topic.description}\n\n"
        f"Content:\n{snippet}\n\n"
        "Reply with YES or NO and one short reason."
    )
    try:
        reply = provider.analyze_text(prompt, system="You classify capture relevance.")
    except LLMError as exc:
        return DiagnosticStep(
            kind="llm_judge",
            value="(YES/NO classifier)",
            passed=False,
            notes=f"Provider failed: {exc}",
        )
    cleaned = reply.strip()
    passed = cleaned.upper().startswith("Y")
    return DiagnosticStep(
        kind="llm_judge",
        value="(YES/NO classifier)",
        passed=passed,
        matched_text=cleaned[:200] if passed else None,
        closest_text=cleaned[:200] if not passed else None,
        notes="LLM judge answered " + ("YES." if passed else "NO."),
    )


def _window(text: str, start: int, end: int) -> str:
    lo = max(0, start - _PREVIEW_RADIUS)
    hi = min(len(text), end + _PREVIEW_RADIUS)
    snippet = text[lo:hi].replace("\n", " ").strip()
    if lo > 0:
        snippet = "…" + snippet
    if hi < len(text):
        snippet = snippet + "…"
    return snippet


def _closest_substring(text: str, needle: str) -> str | None:
    if not text or not needle:
        return None
    chunks: list[str] = []
    for part in re.split(r"\s+", text):
        part = part.strip(" \t\r\n.,;:!?()[]{}\"'")
        if part:
            chunks.append(part)
    if not chunks:
        return None
    matches = difflib.get_close_matches(needle.lower(), [c.lower() for c in chunks], n=1, cutoff=0.6)
    if not matches:
        return None
    best = matches[0]
    # Find original casing in the chunk list.
    for original in chunks:
        if original.lower() == best:
            return original
    return best


__all__ = [
    "DiagnosticResult",
    "DiagnosticStep",
    "diagnose_topic_against_capture",
]

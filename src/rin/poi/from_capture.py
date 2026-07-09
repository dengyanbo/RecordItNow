"""Phase 2-B (v0.15.0): single-capture POI mining.

Given a capture ID, return a partially-populated :class:`TopicSpec`
that the user can edit + accept in the existing PoI editor. Reuses the
regex / phrase / domain patterns from :mod:`rin.poi.discovery` but
runs them on exactly one capture (and skips the "min N captures"
threshold that discovery applies).
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

from ..skills.builtin.topic.skill import TopicSpec
from ._captext import load_capture_text
from .discovery import (
    _DOMAIN_RE,
    _PHRASE_NAME_RE,
    _PHRASE_SPLIT_RE,
    _REGEX_PATTERNS,
    _mostly_title_or_upper,
    _normalize_text,
    extract_evidence_quote,
)

# Hard cap so a chatty capture doesn't return 200 keyword candidates.
MAX_KEYWORDS_PER_CAPTURE = 8
MAX_REGEX_PATTERNS_PER_CAPTURE = 4
SUGGESTED_NAME_FALLBACK = "New PoI"


@dataclass(slots=True, frozen=True)
class CaptureSeed:
    """Bundle returned to the UI for pre-filling the editor dialog."""

    capture_id: int
    topic: TopicSpec
    evidence_quote: str | None


def mine_topic_from_capture(capture_id: int) -> CaptureSeed | None:
    """Return a :class:`TopicSpec` seeded from one capture's text.

    Picks the strongest signal it can find:

    1. Regex ID hit (e.g. ``INC1234567``) → `name = matched token`,
       `regex = [matched pattern]`.
    2. Otherwise the first 2-3 word noun-phrase-ish phrase from the
       summary (``Project Atlas``) → `name = phrase`,
       `keywords = [phrase]`.
    3. Otherwise the first prominent domain (``contoso.example.com``)
       → `name = domain`, `keywords = [domain]`.
    4. If none of the above hit → fallback name from the summary's
       first ~30 chars, no patterns. The user still gets a partially
       filled form they can edit.

    Returns ``None`` if the capture doesn't exist.
    """

    bundle = load_capture_text(capture_id)
    if bundle is None:
        return None
    text, summary = bundle

    text = text or ""
    summary = summary or ""

    name, kind, regex_patterns, keywords, span, source_text = _pick_strongest(
        text=text, summary=summary
    )
    evidence_quote: str | None = None
    if span is not None and source_text:
        evidence_quote = extract_evidence_quote(
            source_text, span[0], span[1]
        )
    elif summary:
        snippet = summary.strip().splitlines()[0]
        evidence_quote = (snippet[:120] + "…") if len(snippet) > 120 else snippet

    if not name:
        if summary:
            fallback = summary.strip().split("\n", 1)[0]
            name = fallback[:30].strip() or SUGGESTED_NAME_FALLBACK
        else:
            name = SUGGESTED_NAME_FALLBACK

    return CaptureSeed(
        capture_id=capture_id,
        topic=TopicSpec(
            name=name,
            description=(summary.strip().split("\n", 1)[0][:140] if summary else ""),
            keywords=keywords[:MAX_KEYWORDS_PER_CAPTURE],
            regex=regex_patterns[:MAX_REGEX_PATTERNS_PER_CAPTURE],
        ),
        evidence_quote=evidence_quote,
    )


def _pick_strongest(
    *, text: str, summary: str
) -> tuple[str, str, list[str], list[str], tuple[int, int] | None, str]:
    """Pick the single strongest signal from a capture's text.

    Returns ``(name, kind, regex_patterns, keywords, span, source_text)``.
    ``span`` and ``source_text`` describe where the match came from so
    the caller can build an evidence quote.
    """

    for raw_pattern in _REGEX_PATTERNS:
        compiled = re.compile(raw_pattern, re.IGNORECASE)
        match = compiled.search(text)
        if match is None:
            continue
        token = _normalize_text(match.group(0)).upper()
        return (
            token,
            "regex",
            [raw_pattern],
            [token],
            (match.start(), match.end()),
            text,
        )

    phrase, phrase_idx = _first_phrase(summary)
    if phrase is not None:
        return (
            phrase,
            "phrase",
            [],
            [phrase],
            (phrase_idx, phrase_idx + len(phrase)),
            summary,
        )

    domain_match = _DOMAIN_RE.search(text)
    if domain_match is not None:
        host = (
            domain_match.group(1)
            .strip()
            .lower()
            .rstrip(".,;:!?)\"']}")
        )
        host = host.removeprefix("www.").split(":", 1)[0]
        if host and host not in {"localhost", "127.0.0.1"} and not host.endswith(".local"):
            return (
                host,
                "domain",
                [],
                [host],
                (domain_match.start(1), domain_match.end(1)),
                text,
            )

    return "", "fallback", [], [], None, ""


def _first_phrase(summary: str) -> tuple[str | None, int]:
    if not summary:
        return None, -1
    tokens = [token for token in _PHRASE_SPLIT_RE.split(summary) if token]
    if len(tokens) < 2:
        return None, -1
    seen: OrderedDict[str, None] = OrderedDict()
    for width in (2, 3):
        for start in range(len(tokens) - width + 1):
            words = tokens[start : start + width]
            if not _mostly_title_or_upper(words):
                continue
            phrase = " ".join(words)
            if not _PHRASE_NAME_RE.fullmatch(phrase):
                continue
            seen.setdefault(phrase, None)
    for phrase in seen:
        idx = summary.find(phrase)
        if idx >= 0:
            return phrase, idx
    return None, -1


__all__ = ["CaptureSeed", "mine_topic_from_capture"]

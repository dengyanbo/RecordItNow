"""Phase 2-A (v0.14.0): evidence quotes + live preview for PoI authoring.

Tests cover:
- `extract_evidence_quote` window math + ellipsis behavior.
- All four discovery strategies attach a quote.
- `_merge_candidates` keeps a non-empty quote when merging duplicates.
- `persist_candidates` writes the quote to the DB.
- `preview_matches` returns count + examples + handles invalid regex
  / empty / no-captures paths.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.poi.discovery import (
    EVIDENCE_QUOTE_MAX_LEN,
    PoICandidateDraft,
    _merge_candidates,
    discover,
    extract_evidence_quote,
    persist_candidates,
)
from rin.poi.preview import preview_matches
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Capture, PoICandidate


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


# ---------------------------------------------------------------------------
# extract_evidence_quote
# ---------------------------------------------------------------------------


def test_extract_quote_pads_ellipses_when_truncating() -> None:
    text = "a" * 100 + "FOO" + "b" * 100
    quote = extract_evidence_quote(text, 100, 103, context=20)
    assert quote.startswith("…")
    assert quote.endswith("…")
    assert "FOO" in quote


def test_extract_quote_returns_full_text_when_short() -> None:
    text = "short FOO bar"
    quote = extract_evidence_quote(text, 6, 9, context=60)
    assert "FOO" in quote
    assert not quote.startswith("…")
    assert not quote.endswith("…")


def test_extract_quote_collapses_whitespace() -> None:
    text = "alpha\n\n   beta\tFOO\n  gamma"
    quote = extract_evidence_quote(text, text.index("FOO"), text.index("FOO") + 3, context=20)
    assert "\n" not in quote
    assert "\t" not in quote
    assert "FOO" in quote


def test_extract_quote_respects_max_len() -> None:
    text = "FOO" + "a" * (EVIDENCE_QUOTE_MAX_LEN * 4)
    quote = extract_evidence_quote(text, 0, 3, context=EVIDENCE_QUOTE_MAX_LEN * 3)
    assert len(quote) <= EVIDENCE_QUOTE_MAX_LEN


def test_extract_quote_empty_text_returns_empty() -> None:
    assert extract_evidence_quote("", 0, 0) == ""
    assert extract_evidence_quote("abc", 2, 2) == ""


# ---------------------------------------------------------------------------
# Discovery strategies surface evidence quotes
# ---------------------------------------------------------------------------


def _insert_capture(
    when: datetime,
    summary: str = "",
    *,
    ocr: str = "",
) -> int:
    with session() as s:
        capture = Capture(kind="screenshot", status="analyzed", started_at=when)
        s.add(capture)
        s.flush()
        s.add(Analysis(capture_id=capture.id, summary=summary, ocr_text=ocr))
        s.flush()
        return capture.id


def test_discover_regex_attaches_quote(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    _insert_capture(
        base,
        summary="Working on INC1234567 with the customer",
        ocr="INC1234567 ticket details",
    )
    _insert_capture(
        base + timedelta(hours=1),
        summary="Closed INC1234567 finally",
    )

    cfg = RinConfig()
    drafts = discover(cfg, days=14, use_llm=False)
    regex_draft = next(d for d in drafts if d.kind == "regex")
    assert regex_draft.suggested_name == "INC1234567"
    assert regex_draft.evidence_quote
    assert "INC1234567" in regex_draft.evidence_quote


def test_discover_domain_attaches_quote(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    text = (
        "Long context about the workflow at https://contoso.example.com/path "
        "and more notes about the rollout schedule."
    )
    _insert_capture(base, ocr=text)
    _insert_capture(base + timedelta(hours=1), ocr=text)

    cfg = RinConfig()
    drafts = discover(cfg, days=14, use_llm=False)
    domain_draft = next(
        d for d in drafts if d.kind == "domain" and "contoso" in d.suggested_name
    )
    assert domain_draft.evidence_quote
    assert "contoso" in domain_draft.evidence_quote


def test_discover_phrase_attaches_quote(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    _insert_capture(
        base,
        summary="Project Atlas kicked off with a long preparation phase across teams",
    )
    _insert_capture(
        base + timedelta(hours=1),
        summary="Continued Project Atlas review meeting agenda this morning",
    )

    cfg = RinConfig()
    drafts = discover(cfg, days=14, use_llm=False)
    phrase_draft = next(d for d in drafts if d.kind == "phrase")
    assert phrase_draft.suggested_name == "Project Atlas"
    assert phrase_draft.evidence_quote
    assert "Project Atlas" in phrase_draft.evidence_quote


# ---------------------------------------------------------------------------
# Merge + persist
# ---------------------------------------------------------------------------


def test_merge_candidates_prefers_non_empty_quote() -> None:
    a = PoICandidateDraft(
        suggested_name="Atlas",
        kind="phrase",
        description=None,
        evidence_capture_ids=[1],
        score=2.0,
        evidence_quote=None,
    )
    b = PoICandidateDraft(
        suggested_name="Atlas",
        kind="phrase",
        description=None,
        evidence_capture_ids=[2],
        score=1.0,
        evidence_quote="…Project Atlas review…",
    )
    [merged] = _merge_candidates([a, b])
    assert merged.evidence_quote == "…Project Atlas review…"


def test_persist_candidates_writes_evidence_quote(rin_db: Path) -> None:
    draft = PoICandidateDraft(
        suggested_name="Atlas",
        kind="phrase",
        description="Project Atlas",
        evidence_capture_ids=[1, 2],
        score=2.0,
        evidence_quote="…Project Atlas review…",
    )
    ids = persist_candidates([draft])
    assert len(ids) == 1
    with session() as s:
        row = s.get(PoICandidate, ids[0])
        assert row is not None
        assert row.evidence_quote == "…Project Atlas review…"
        assert json.loads(row.evidence_capture_ids) == [1, 2]


def test_persist_candidates_handles_none_quote(rin_db: Path) -> None:
    draft = PoICandidateDraft(
        suggested_name="Beta",
        kind="phrase",
        description=None,
        evidence_capture_ids=[1],
        score=1.0,
        evidence_quote=None,
    )
    ids = persist_candidates([draft])
    with session() as s:
        row = s.get(PoICandidate, ids[0])
        assert row is not None
        assert row.evidence_quote is None


# ---------------------------------------------------------------------------
# Live preview
# ---------------------------------------------------------------------------


def test_preview_matches_returns_count_and_examples(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    _insert_capture(base, summary="Working on Atlas design today.")
    _insert_capture(base + timedelta(hours=1), summary="Atlas review meeting recap")
    _insert_capture(base + timedelta(hours=2), summary="Unrelated note about lunch")

    result = preview_matches(keywords=["Atlas"], days=14, max_examples=3)
    assert result.matched_count == 2
    assert result.sampled_captures == 3
    assert result.error is None
    assert len(result.examples) == 2
    for example in result.examples:
        assert "Atlas" in example.snippet


def test_preview_matches_supports_regex(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    _insert_capture(base, summary="Ticket INC1234567 follow-up")
    _insert_capture(base + timedelta(hours=1), summary="INC9999999 retro")
    _insert_capture(base + timedelta(hours=2), summary="Unrelated")

    result = preview_matches(
        regex_patterns=[r"INC\d{7}"], days=14, max_examples=3
    )
    assert result.matched_count == 2
    assert all("INC" in ex.snippet.upper() for ex in result.examples)


def test_preview_matches_returns_error_on_invalid_regex(rin_db: Path) -> None:
    result = preview_matches(regex_patterns=["[unclosed"], days=14)
    assert result.error is not None
    assert "Invalid regex" in result.error
    assert result.matched_count == 0
    assert result.examples == []


def test_preview_matches_returns_zero_when_no_inputs(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    _insert_capture(base, summary="anything goes here")
    result = preview_matches(regex_patterns=[], keywords=[], days=14)
    assert result.matched_count == 0
    assert result.examples == []
    assert result.sampled_captures == 0


def test_preview_matches_returns_zero_when_no_captures(rin_db: Path) -> None:
    result = preview_matches(keywords=["whatever"], days=14)
    assert result.matched_count == 0
    assert result.sampled_captures == 0
    assert result.error is None


def test_preview_matches_caps_example_count(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    for i in range(10):
        _insert_capture(
            base + timedelta(minutes=i),
            summary=f"Atlas planning session number {i}",
        )
    result = preview_matches(keywords=["Atlas"], days=14, max_examples=3)
    assert result.matched_count == 10
    assert len(result.examples) == 3


def test_preview_matches_sample_limit_caps_scan(rin_db: Path) -> None:
    base = datetime.now() - timedelta(days=1)
    for i in range(15):
        _insert_capture(
            base + timedelta(minutes=i),
            summary=f"Atlas planning session number {i}",
        )
    result = preview_matches(
        keywords=["Atlas"], days=14, max_examples=3, sample_limit=5
    )
    assert result.sampled_captures == 5
    assert result.matched_count == 5

"""Tests for PoI discovery and persistence."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.poi import PoICandidateDraft, discover, persist_candidates
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Capture, PoICandidate, Transcript


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Spin up a fresh SQLite DB in a tmp directory and tear it down."""

    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls: list[str] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="")

    def analyze_text(self, prompt, *, system=None):
        self.calls.append(prompt)
        return self.response

    def chat(self, messages):
        return ""


def _insert_capture(
    when: datetime,
    summary: str,
    *,
    ocr: str = "",
    transcript: str = "",
) -> int:
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="analyzed",
            started_at=when,
            ended_at=when,
        )
        s.add(cap)
        s.flush()
        s.add(
            Analysis(
                capture_id=cap.id,
                summary=summary,
                ocr_text=ocr or None,
            )
        )
        if transcript:
            s.add(Transcript(capture_id=cap.id, text=transcript))
        s.flush()
        return cap.id


def _candidate_by_name(
    drafts: list[PoICandidateDraft],
    name: str,
) -> PoICandidateDraft:
    return next(draft for draft in drafts if draft.suggested_name == name)


def test_regex_mining_surfaces_inc_ids(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    evidence_ids = [
        _insert_capture(now - timedelta(days=3), "INC0099999 opened by customer"),
        _insert_capture(now - timedelta(days=2), "working incident", ocr="Ticket INC0099999"),
        _insert_capture(
            now - timedelta(days=1),
            "review notes",
            transcript="We resolved INC0099999 after restart.",
        ),
    ]
    _insert_capture(now - timedelta(hours=4), "unrelated capture")
    _insert_capture(now - timedelta(hours=1), "another unrelated capture")

    drafts = discover(RinConfig(), now=now, days=14)

    candidate = _candidate_by_name(drafts, "INC0099999")
    assert candidate.kind == "regex"
    assert candidate.evidence_capture_ids == evidence_ids


def test_regex_mining_below_min_evidence_dropped(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    _insert_capture(now - timedelta(days=1), "Only once: INC0099999")
    _insert_capture(now - timedelta(hours=2), "still unrelated")

    drafts = discover(RinConfig(), now=now, days=14)

    assert all(draft.suggested_name != "INC0099999" for draft in drafts)


def test_domain_mining_groups_by_host(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    github_ids = [
        _insert_capture(
            now - timedelta(days=index),
            "checking links",
            ocr="visit https://github.com/foo and https://github.com/bar",
        )
        for index in range(4)
    ]
    gitlab_ids = [
        _insert_capture(
            now - timedelta(days=5 + index),
            "more links",
            ocr="browse https://gitlab.example.com/group/repo",
        )
        for index in range(2)
    ]

    drafts = discover(RinConfig(), now=now, days=14)

    github = _candidate_by_name(drafts, "github.com")
    gitlab = _candidate_by_name(drafts, "gitlab.example.com")
    assert github.kind == "domain"
    assert github.evidence_capture_ids == github_ids
    assert gitlab.evidence_capture_ids == gitlab_ids


def test_domain_mining_strips_www(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    evidence_ids = [
        _insert_capture(
            now - timedelta(days=1),
            "links one",
            ocr="visit https://www.example.com/docs",
        ),
        _insert_capture(
            now - timedelta(hours=4),
            "links two",
            ocr="visit https://example.com/pricing",
        ),
    ]

    drafts = discover(RinConfig(), now=now, days=14)

    candidate = _candidate_by_name(drafts, "example.com")
    assert candidate.kind == "domain"
    assert candidate.evidence_capture_ids == evidence_ids


def test_phrase_mining_finds_titlecase_bigrams(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    atlas_ids = [
        _insert_capture(now - timedelta(days=3), "Working on Project Atlas rollout"),
        _insert_capture(now - timedelta(days=2), "Project Atlas status update"),
        _insert_capture(now - timedelta(days=1), "Reviewed Project Atlas docs"),
    ]
    _insert_capture(now - timedelta(hours=3), "the the")

    drafts = discover(RinConfig(), now=now, days=14)

    candidate = _candidate_by_name(drafts, "Project Atlas")
    assert candidate.kind == "phrase"
    assert candidate.evidence_capture_ids == atlas_ids
    assert all(draft.suggested_name.lower() != "the the" for draft in drafts)


def test_discover_filters_already_tracked_topics(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    _insert_capture(now - timedelta(days=1), "atlas planning note")
    _insert_capture(now - timedelta(hours=2), "atlas follow-up")
    cfg = RinConfig(
        skills={
            "topic": {
                "topics": [
                    {
                        "name": "Atlas",
                        "aliases": ["Project Atlas"],
                        "keywords": ["atlas"],
                    }
                ]
            }
        }
    )
    provider = _FakeProvider(
        '{"name": "Atlas", "description": "Recurring internal project."}'
    )

    drafts = discover(cfg, now=now, days=14, use_llm=True, provider=provider)

    assert all(draft.suggested_name != "Atlas" for draft in drafts)


def test_persist_candidates_inserts_and_dedupes(rin_db) -> None:
    drafts = [
        PoICandidateDraft("Atlas", "llm", "project", [1, 2], 0.5),
        PoICandidateDraft("github.com", "domain", "domain", [3, 4], 1.0),
        PoICandidateDraft("INC0099999", "regex", "ticket", [5, 6], 2.0),
    ]

    inserted = persist_candidates(drafts)
    inserted_again = persist_candidates(drafts)

    assert len(inserted) == 3
    assert inserted_again == []
    with session() as s:
        rows = s.scalars(select(PoICandidate).order_by(PoICandidate.id)).all()
    assert len(rows) == 3
    assert all(row.status == "pending" for row in rows)
    assert all(row.decided_by == "auto" for row in rows)


def test_llm_mining_called_only_when_use_llm_true(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    _insert_capture(now - timedelta(days=1), "acme planning note")
    _insert_capture(now - timedelta(hours=2), "acme customer follow-up")
    provider = _FakeProvider(
        '{"name": "Acme", "description": "Recurring customer."}'
    )

    discover(RinConfig(), now=now, days=14, use_llm=False, provider=provider)
    assert provider.calls == []

    discover(RinConfig(), now=now, days=14, use_llm=True, provider=provider)
    assert len(provider.calls) == 1


def test_llm_mining_tolerates_malformed_lines(rin_db) -> None:
    now = datetime(2026, 1, 15, 12, 0, 0)
    _insert_capture(now - timedelta(days=1), "atlas planning and beacon review")
    _insert_capture(now - timedelta(hours=2), "beacon follow-up with atlas team")
    provider = _FakeProvider(
        "\n".join(
            [
                '{"name": "Atlas", "description": "Recurring project."}',
                "not json at all",
                '{"description": "missing name"}',
                '{"name": "Beacon", "description": "Recurring customer."}',
            ]
        )
    )

    drafts = discover(RinConfig(), now=now, days=14, use_llm=True, provider=provider)

    names = {draft.suggested_name for draft in drafts if draft.kind == "llm"}
    assert names == {"Atlas", "Beacon"}


def test_cli_poi_discover_runs_and_persists(rin_db, capsys: pytest.CaptureFixture[str]) -> None:
    now = datetime.now()
    for offset in range(3):
        _insert_capture(
            now - timedelta(days=offset),
            "incident work",
            ocr="INC0099999 still active",
        )

    from rin.__main__ import main

    rc = main(["poi-discover", "--days", "30", "--persist"])

    assert rc == 0
    with session() as s:
        rows = s.scalars(select(PoICandidate)).all()
    assert rows
    assert any(row.suggested_name == "INC0099999" for row in rows)

    out = capsys.readouterr().out
    assert "INC0099999" in out
    assert "Saved 1 new candidates to DB." in out
    payload = json.loads(rows[0].evidence_capture_ids)
    assert payload == [1, 2, 3]

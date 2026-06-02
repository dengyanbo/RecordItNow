"""Tests for the Settings → Topics & PoIs tab."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.storage import db, init_db, session
from rin.storage.models import PoICandidate
from rin.ui.poi_tab import TopicsAndPoIsTab


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _insert_candidate(
    *,
    name: str,
    kind: str = "phrase",
    status: str = "pending",
    score: float = 1.0,
    description: str | None = None,
    evidence_ids: list[int] | None = None,
) -> int:
    with session() as s:
        row = PoICandidate(
            suggested_name=name,
            kind=kind,
            description=description,
            evidence_capture_ids=json.dumps(evidence_ids or [1, 2]),
            score=score,
            status=status,
            decided_by="auto",
        )
        s.add(row)
        s.flush()
        return row.id


def _add_manual_poi(
    tab: TopicsAndPoIsTab,
    *,
    name: str,
    description: str = "",
    keywords: str = "",
    regex: str = "",
    llm_judge: bool = False,
    archive_after_days: int = 30,
    closed_phrases: str = "",
) -> None:
    tab._manual_name.setText(name)
    tab._manual_description.setText(description)
    tab._manual_keywords.setText(keywords)
    tab._manual_regex.setPlainText(regex)
    tab._manual_llm_judge.setChecked(llm_judge)
    tab._manual_archive_after_days.setValue(archive_after_days)
    tab._manual_closed_phrases.setPlainText(closed_phrases)
    tab._on_add_manual_poi()


def test_tab_loads_empty_when_no_pois_configured(qapp) -> None:
    tab = TopicsAndPoIsTab(RinConfig())

    assert tab._my_pois_table.rowCount() == 0
    assert tab._suggested_table.rowCount() == 0


def test_add_manual_poi_appears_in_table(qapp) -> None:
    tab = TopicsAndPoIsTab(RinConfig())

    _add_manual_poi(
        tab,
        name="Project Atlas",
        description="Migration workstream",
        keywords="atlas, migration",
        regex=r"ATLAS-\d+",
        llm_judge=True,
        archive_after_days=21,
    )

    assert tab._my_pois_table.rowCount() == 1
    assert tab._my_pois_table.item(0, 0).text() == "Project Atlas"
    assert tab._my_pois_table.item(0, 1).text() == "Migration workstream"
    assert tab._my_pois_table.item(0, 4).text() == "Yes"


def test_commit_to_config_writes_topics_to_skills_config(qapp) -> None:
    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)

    _add_manual_poi(tab, name="Atlas", keywords="atlas")
    _add_manual_poi(tab, name="Roadmap", keywords="roadmap", archive_after_days=14)
    tab.commit_to_config()

    section = cfg.skills.config_for_skill("topic")
    assert section is not None
    assert [row["name"] for row in section["topics"]] == ["Atlas", "Roadmap"]
    assert section["topics"][1]["archive_after_days"] == 14


def test_commit_to_config_adds_topic_to_enabled_when_first_poi_added(qapp) -> None:
    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)

    _add_manual_poi(tab, name="Atlas", keywords="atlas")
    tab.commit_to_config()

    assert "topic" in cfg.skills.enabled


def test_suggested_candidates_loaded_from_db(qapp, rin_db) -> None:
    _insert_candidate(name="Atlas")
    _insert_candidate(name="Contoso", kind="domain")

    tab = TopicsAndPoIsTab(RinConfig())

    assert tab._suggested_table.rowCount() == 2


def test_accept_candidate_appends_to_my_pois_and_marks_db(qapp, rin_db) -> None:
    candidate_id = _insert_candidate(
        name="Project Atlas",
        description="Migration workstream",
        evidence_ids=[1, 2, 3],
    )
    tab = TopicsAndPoIsTab(RinConfig())

    tab._on_accept_candidate(candidate_id)

    assert tab._my_pois_table.rowCount() == 1
    assert tab._my_pois_table.item(0, 0).text() == "Project Atlas"
    assert tab._suggested_table.rowCount() == 0
    with session() as s:
        row = s.get(PoICandidate, candidate_id)
        assert row is not None
        assert row.status == "accepted"
        assert row.decided_by == "user"


def test_reject_candidate_marks_db_only(qapp, rin_db) -> None:
    candidate_id = _insert_candidate(name="Ignore Me")
    tab = TopicsAndPoIsTab(RinConfig())

    tab._on_reject_candidate(candidate_id)

    assert tab._my_pois_table.rowCount() == 0
    assert tab._suggested_table.rowCount() == 0
    with session() as s:
        row = s.get(PoICandidate, candidate_id)
        assert row is not None
        assert row.status == "rejected"
        assert row.decided_by == "user"


def test_invalid_regex_in_form_shows_error_does_not_add(qapp) -> None:
    tab = TopicsAndPoIsTab(RinConfig())
    tab.show()
    qapp.processEvents()

    _add_manual_poi(tab, name="Broken", regex="[invalid")
    qapp.processEvents()

    assert tab._my_pois_table.rowCount() == 0
    assert tab._manual_error_label.isVisible()
    assert "Invalid regex" in tab._manual_error_label.text()

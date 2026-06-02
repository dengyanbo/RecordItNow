"""Tests for the PoI setup wizard."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.poi.discovery import PoICandidateDraft
from rin.storage import db, init_db, session
from rin.storage.models import PoICandidate
from rin.ui.poi_wizard import PoIWizard


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _make_draft(name: str, *, evidence_ids: list[int] | None = None) -> PoICandidateDraft:
    return PoICandidateDraft(
        suggested_name=name,
        kind="phrase",
        description=f"About {name}",
        evidence_capture_ids=evidence_ids or [1, 2],
        score=1.0,
    )


def _insert_candidate(name: str, *, evidence_ids: list[int] | None = None) -> int:
    with session() as s:
        row = PoICandidate(
            suggested_name=name,
            kind="phrase",
            description=f"About {name}",
            evidence_capture_ids=json.dumps(evidence_ids or [1, 2]),
            score=1.0,
            status="pending",
            decided_by="auto",
        )
        s.add(row)
        s.flush()
        return row.id


def _drain(qapp, rounds: int = 3) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def _make_sync_wizard(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
    drafts: list[PoICandidateDraft] | None = None,
) -> PoIWizard:
    import rin.poi.discovery as discovery_mod

    monkeypatch.setattr(
        discovery_mod,
        "discover",
        lambda cfg, days=14, use_llm=False: list(drafts or []),
    )
    wizard = PoIWizard(RinConfig())
    monkeypatch.setattr(wizard._discovery_page, "_start_task", lambda task: task.run())
    wizard.show()
    _drain(qapp)
    return wizard


def _advance_to_confirm(wizard: PoIWizard, qapp) -> None:
    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)


def test_wizard_constructs_with_empty_cfg(qapp, rin_db, monkeypatch: pytest.MonkeyPatch) -> None:
    wizard = _make_sync_wizard(qapp, monkeypatch, [])

    assert wizard.pageIds() == [0, 1, 2, 3]
    assert wizard.currentId() == 0

    wizard.next()
    _drain(qapp)
    assert wizard.currentId() == 1

    wizard.next()
    _drain(qapp)
    assert wizard.currentId() == 2
    assert wizard._discovery_page.isComplete()

    wizard.next()
    _drain(qapp)
    assert wizard.currentId() == 3


def test_skip_path_sets_poi_wizard_seen_and_no_topics_added(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = RinConfig()
    import rin.poi.discovery as discovery_mod

    monkeypatch.setattr(discovery_mod, "discover", lambda cfg, days=14, use_llm=False: [])
    wizard = PoIWizard(cfg)
    monkeypatch.setattr(wizard._discovery_page, "_start_task", lambda task: task.run())
    wizard.show()
    _advance_to_confirm(wizard, qapp)

    wizard.accept()

    section = cfg.skills.config_for_skill("topic")
    assert cfg.skills.poi_wizard_seen is True
    assert section is None or section.get("topics") == []
    assert "topic" not in cfg.skills.enabled


def test_declare_path_writes_topic_to_config(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = RinConfig()
    import rin.poi.discovery as discovery_mod

    monkeypatch.setattr(discovery_mod, "discover", lambda cfg, days=14, use_llm=False: [])
    wizard = PoIWizard(cfg)
    monkeypatch.setattr(wizard._discovery_page, "_start_task", lambda task: task.run())
    wizard.show()
    _drain(qapp)

    wizard.next()
    _drain(qapp)
    row = wizard._manual_page._rows[0]
    row.name_edit.setText("MyProject")
    row.add_button.click()
    _drain(qapp)

    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)
    wizard.accept()

    section = cfg.skills.config_for_skill("topic")
    assert section is not None
    assert [topic["name"] for topic in section["topics"]] == ["MyProject"]
    assert "topic" in cfg.skills.enabled
    assert cfg.skills.poi_wizard_seen is True


def test_discovery_path_accepts_checked_candidates(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = RinConfig()
    drafts = [_make_draft("Atlas"), _make_draft("Contoso", evidence_ids=[1, 2, 3])]
    import rin.poi.discovery as discovery_mod

    monkeypatch.setattr(
        discovery_mod,
        "discover",
        lambda cfg, days=14, use_llm=False: list(drafts),
    )
    wizard = PoIWizard(cfg)
    monkeypatch.setattr(wizard._discovery_page, "_start_task", lambda task: task.run())
    wizard.show()

    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)

    assert len(wizard._discovery_page._checks) == 2
    assert all(checkbox.isChecked() for _, checkbox in wizard._discovery_page._checks)

    wizard.next()
    _drain(qapp)
    wizard.accept()

    section = cfg.skills.config_for_skill("topic")
    assert section is not None
    assert [topic["name"] for topic in section["topics"]] == ["Atlas", "Contoso"]


def test_discovery_path_uncheck_drops_candidate(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = RinConfig()
    drafts = [_make_draft("Atlas"), _make_draft("Contoso")]
    import rin.poi.discovery as discovery_mod

    monkeypatch.setattr(
        discovery_mod,
        "discover",
        lambda cfg, days=14, use_llm=False: list(drafts),
    )
    wizard = PoIWizard(cfg)
    monkeypatch.setattr(wizard._discovery_page, "_start_task", lambda task: task.run())
    wizard.show()

    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)

    wizard._discovery_page._checks[1][1].setChecked(False)
    wizard.next()
    _drain(qapp)
    wizard.accept()

    section = cfg.skills.config_for_skill("topic")
    assert section is not None
    assert [topic["name"] for topic in section["topics"]] == ["Atlas"]


def test_accept_marks_db_candidates_when_present(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _insert_candidate("Atlas")
    _insert_candidate("Contoso")
    cfg = RinConfig()
    drafts = [_make_draft("Atlas"), _make_draft("Contoso")]
    import rin.poi.discovery as discovery_mod

    monkeypatch.setattr(
        discovery_mod,
        "discover",
        lambda cfg, days=14, use_llm=False: list(drafts),
    )
    wizard = PoIWizard(cfg)
    monkeypatch.setattr(wizard._discovery_page, "_start_task", lambda task: task.run())
    wizard.show()

    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)
    wizard.accept()

    with session() as s:
        rows = s.scalars(select(PoICandidate).order_by(PoICandidate.id.asc())).all()
        assert [row.status for row in rows] == ["accepted", "accepted"]
        assert all(row.decided_by == "user" for row in rows)

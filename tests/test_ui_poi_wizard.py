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


def test_discovery_page_renders_evidence_quote(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 2-A: each suggestion shows the matched snippet underneath."""

    from PySide6.QtWidgets import QLabel

    drafts = [
        PoICandidateDraft(
            suggested_name="Atlas",
            kind="phrase",
            description="Project Atlas",
            evidence_capture_ids=[1, 2, 3],
            score=2.0,
            evidence_quote="…Project Atlas review meeting agenda…",
        ),
    ]
    wizard = _make_sync_wizard(qapp, monkeypatch, drafts)

    wizard.next()
    _drain(qapp)
    wizard.next()
    _drain(qapp)

    labels = wizard._discovery_page._results_host.findChildren(QLabel)
    label_texts = [label.text() for label in labels]
    assert any(
        "Project Atlas review meeting agenda" in text for text in label_texts
    )


def test_manual_page_persona_dropdown_prepopulates_topics(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 2-B: selecting a persona pre-populates the wizard's manual page."""

    wizard = _make_sync_wizard(qapp, monkeypatch, [])
    wizard.next()
    _drain(qapp)

    page = wizard._manual_page
    combo = page._persona_combo
    # Default selection is "Custom" → no topics yet.
    assert combo.currentData() == ""
    assert page.added_topics() == []

    engineer_index = combo.findData("engineer")
    assert engineer_index > 0
    combo.setCurrentIndex(engineer_index)
    _drain(qapp)

    added = page.added_topics()
    assert len(added) > 0
    assert any(topic.name == "Pull Requests" for topic in added)


def test_manual_page_persona_then_manual_add_coexist(
    qapp,
    rin_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 2-B: after a 4-topic persona pack, manual add still works."""

    wizard = _make_sync_wizard(qapp, monkeypatch, [])
    wizard.next()
    _drain(qapp)

    page = wizard._manual_page
    combo = page._persona_combo
    combo.setCurrentIndex(combo.findData("engineer"))
    _drain(qapp)

    row = page._rows[0]
    assert row.add_button.isEnabled()
    row.name_edit.setText("My side project")
    row.add_button.click()
    _drain(qapp)

    names = [topic.name for topic in page.added_topics()]
    assert "My side project" in names

"""UI tests for the Phase 2-C diagnostic dialog."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.skills.builtin.topic.skill import TopicSpec
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Capture
from rin.ui.poi_diagnostic_dialog import PoIDiagnosticDialog


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _insert(summary: str, *, ocr: str = "") -> int:
    when = datetime.now()
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", started_at=when, ended_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=summary, ocr_text=ocr or None))
        s.flush()
        return cap.id


def test_diagnostic_dialog_renders_pass_and_fail(qapp, rin_db: Path) -> None:
    from PySide6.QtWidgets import QLabel

    cap_id = _insert("Working on Project Atlas migration today.")
    topic = TopicSpec(
        name="Atlas", keywords=["Atlas", "missing"], regex=[r"ATLAS-\d+"]
    )

    dialog = PoIDiagnosticDialog(topic, provider=None)
    dialog.run_against_capture(cap_id)
    qapp.processEvents()

    result = dialog.result()
    assert result is not None
    assert result.overall_match  # keyword Atlas should match

    label_texts = [
        label.text() for label in dialog._steps_host.findChildren(QLabel)
    ]
    # At least one pass row and one fail row.
    assert any("✅" in text and "Atlas" in text for text in label_texts)
    assert any("❌" in text and "missing" in text for text in label_texts)


def test_diagnostic_dialog_missing_capture(qapp, rin_db: Path) -> None:
    topic = TopicSpec(name="X", keywords=["x"])
    dialog = PoIDiagnosticDialog(topic, provider=None)
    dialog.run_against_capture(9999)
    qapp.processEvents()

    assert dialog.result() is None
    assert "not found" in dialog._capture_label.text().lower()

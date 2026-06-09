"""UI tests for the "Convert to Skill" button on Topics & PoIs (v0.18.0)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.skills.builtin.topic.skill import TopicSpec
from rin.storage import db, init_db
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


def test_convert_button_present_for_each_topic(qapp, rin_db) -> None:
    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)
    tab._in_memory_topics = [TopicSpec(name="Convertible", keywords=["c"])]
    tab._reload_my_pois_table()

    assert tab._my_pois_table.columnCount() == 10
    convert_widget = tab._my_pois_table.cellWidget(0, 8)
    assert convert_widget is not None
    assert "Convert" in convert_widget.text()


def test_convert_topic_writes_skill_and_removes(
    qapp, rin_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bypass the QMessageBox confirmations and run the actual conversion."""
    from PySide6.QtWidgets import QMessageBox

    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)
    tab._in_memory_topics = [
        TopicSpec(name="To Convert", keywords=["foo"], archive_after_days=14),
        TopicSpec(name="Keep Me", keywords=["bar"]),
    ]
    tab._reload_my_pois_table()

    # Force the confirmation prompt to return Ok, and the success info to
    # return immediately.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    tab._on_convert_topic(0)

    # The PoI is gone from the table.
    assert len(tab._in_memory_topics) == 1
    assert tab._in_memory_topics[0].name == "Keep Me"
    assert tab._my_pois_table.rowCount() == 1

    # The skill.py was actually written under the user skills dir.
    skill_py = paths_mod.skills_dir() / "to_convert" / "skill.py"
    assert skill_py.exists()
    body = skill_py.read_text(encoding="utf-8")
    assert "To Convert" in body
    assert "'foo'" in body


def test_convert_topic_cancelled_keeps_poi(
    qapp, rin_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)
    tab._in_memory_topics = [TopicSpec(name="Cancel Me", keywords=["x"])]
    tab._reload_my_pois_table()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    tab._on_convert_topic(0)

    # Still present; no skill file written.
    assert len(tab._in_memory_topics) == 1
    assert not (paths_mod.skills_dir() / "cancel_me" / "skill.py").exists()


def test_convert_topic_persists_config_atomically(
    qapp, rin_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.18.3 (M1): a successful Convert must write config.toml *immediately*
    so the on-disk skill and the in-config PoI removal stay in sync. Before
    the fix, the removal was deferred until the user clicked Save on the
    Settings dialog — a Cancel would leave the user with both."""
    import tomllib

    from PySide6.QtWidgets import QMessageBox

    from rin import paths as p

    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)
    tab._in_memory_topics = [
        TopicSpec(name="Persist Me", keywords=["pm"]),
        TopicSpec(name="Keep Me", keywords=["km"]),
    ]
    tab._reload_my_pois_table()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    tab._on_convert_topic(0)

    # Skill file written.
    assert (paths_mod.skills_dir() / "persist_me" / "skill.py").exists()

    # config.toml on disk reflects the removal — load fresh and check.
    config_path = p.config_path()
    assert config_path.exists(), "config.toml should have been written"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    topic_section = data.get("skills", {}).get("topic", {})
    names_on_disk = [t.get("name") for t in topic_section.get("topics", [])]
    assert "Persist Me" not in names_on_disk, (
        f"Converted topic should be removed from config.toml; found: {names_on_disk}"
    )
    assert "Keep Me" in names_on_disk


def test_convert_topic_rolls_back_on_save_failure(
    qapp, rin_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.18.3 (M1): if config.save() fails after the file was written,
    restore the PoI and delete the orphaned skill file so the user isn't
    left with a half-applied state."""
    from PySide6.QtWidgets import QMessageBox

    cfg = RinConfig()
    tab = TopicsAndPoIsTab(cfg)
    tab._in_memory_topics = [TopicSpec(name="Doomed", keywords=["d"])]
    tab._reload_my_pois_table()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    critical_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *a, **k: (critical_calls.append((a, k)), QMessageBox.StandardButton.Ok)[1],
    )

    def _boom(*_a, **_k):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(RinConfig, "save", _boom)

    tab._on_convert_topic(0)

    # PoI was restored.
    assert len(tab._in_memory_topics) == 1
    assert tab._in_memory_topics[0].name == "Doomed"
    # Orphan file was cleaned up.
    assert not (paths_mod.skills_dir() / "doomed" / "skill.py").exists()
    # User was told.
    assert critical_calls, "QMessageBox.critical should have been called on rollback"

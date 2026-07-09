"""Settings UI for the Topics & PoIs page."""
from __future__ import annotations

import contextlib
import json
from datetime import datetime

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ..config import RinConfig, SkillsConfig
from ..poi.from_capture import CaptureSeed, mine_topic_from_capture
from ..skills.builtin.topic.skill import TopicConfig, TopicSpec
from ..storage import session
from ..storage.models import PoICandidate
from ..utils.logging import get_logger
from .poi_tab_capture_picker import _CapturePickerDialog
from .poi_tab_discovery import _DiscoverySignals, _DiscoveryTask
from .poi_tab_editor import (
    _topic_from_form_data,
    _TopicEditorDialog,
    _TopicEditorFields,
    _TopicFormData,
)
from .poi_tab_widgets import _card, _configure_table, _hint, _item
from .progress import Spinner
from .theme import current_theme

log = get_logger(__name__)


class TopicsAndPoIsTab(QWidget):
    """The 'Topics & PoIs' page rendered into the Settings stack.

    Reads + writes the cfg.skills config_for_skill('topic') dict in-memory.
    The Settings dialog flushes to TOML on Save.
    """

    pois_changed = Signal()

    def __init__(self, config: RinConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._pool = QThreadPool.globalInstance()
        self._discover_busy = False
        self._topic_section_extras: dict = {}
        self._in_memory_topics: list[TopicSpec] = []
        self._load_topics_from_config()

        self._discovery_signals = _DiscoverySignals()
        self._discovery_signals.done.connect(
            self._on_discovery_done,
            Qt.ConnectionType.QueuedConnection,
        )
        self._discovery_signals.failed.connect(
            self._on_discovery_failed,
            Qt.ConnectionType.QueuedConnection,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        intro = QLabel(
            "Points of Interest (PoIs) are the recurring projects, customers, tickets, or topics you want RIN to group together. "
            "Accepted suggestions update the database immediately, while changes to your configured PoIs are kept in memory until you click Save."
        )
        intro.setProperty("role", "field-hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(self._build_my_pois_section())
        layout.addWidget(self._build_suggested_section())
        layout.addWidget(self._build_manual_section())
        layout.addStretch(1)

        self._reload_my_pois_table()
        self._reload_suggested_table()
        self._sync_discovery_state()

    def commit_to_config(self) -> None:
        write_topics_to_config(
            self._config,
            self._in_memory_topics,
            topic_section_extras=self._topic_section_extras,
        )

    def _build_my_pois_section(self) -> QWidget:
        card, body = _card("My PoIs")

        self._my_pois_table = QTableWidget(0, 10)
        self._my_pois_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Description",
                "Keywords",
                "Regex",
                "LLM judge",
                "Archive after",
                "Edit",
                "Diagnose",
                "Convert",
                "Delete",
            ]
        )
        _configure_table(self._my_pois_table)
        header = self._my_pois_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column in (4, 5, 6, 7, 8, 9):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self._my_pois_table)
        return card

    def _build_suggested_section(self) -> QWidget:
        card, body = _card("Suggested PoIs")

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        wizard_btn = QPushButton("Run wizard…")
        wizard_btn.setProperty("flat", True)
        wizard_btn.setFlat(True)
        wizard_btn.clicked.connect(self._launch_wizard)
        actions.addWidget(wizard_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._discover_button = QPushButton("Discover now…")
        self._discover_button.clicked.connect(self._on_discover_now)
        actions.addWidget(self._discover_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._from_capture_button = QPushButton("Create from capture…")
        self._from_capture_button.setProperty("flat", True)
        self._from_capture_button.setFlat(True)
        self._from_capture_button.clicked.connect(self._on_create_from_capture)
        actions.addWidget(self._from_capture_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._discover_spinner = Spinner(size=18, accent=self._theme().accent)
        self._discover_spinner.hide()
        actions.addWidget(self._discover_spinner, 0, Qt.AlignmentFlag.AlignVCenter)

        self._discover_status = _hint("")
        actions.addWidget(self._discover_status, 0, Qt.AlignmentFlag.AlignVCenter)
        actions.addStretch(1)
        body.addLayout(actions)

        self._suggested_table = QTableWidget(0, 7)
        self._suggested_table.setHorizontalHeaderLabels(
            [
                "Suggested name",
                "Kind",
                "Score",
                "Evidence",
                "Quote",
                "Accept",
                "Reject",
            ]
        )
        _configure_table(self._suggested_table)
        header = self._suggested_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self._suggested_table)
        return card

    def _build_manual_section(self) -> QWidget:
        card, body = _card("Add manually")

        self._manual_fields = _TopicEditorFields(self)
        self._manual_name = self._manual_fields.name_edit
        self._manual_description = self._manual_fields.description_edit
        self._manual_keywords = self._manual_fields.keywords_edit
        self._manual_regex = self._manual_fields.regex_edit
        self._manual_llm_judge = self._manual_fields.llm_judge_check
        self._manual_archive_after_days = self._manual_fields.archive_after_spin
        self._manual_closed_phrases = self._manual_fields.closed_phrases_edit
        self._manual_error_label = self._manual_fields.error_label
        body.addWidget(self._manual_fields)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        self._manual_add_button = QPushButton("Add")
        self._manual_add_button.setProperty("primary", True)
        self._manual_add_button.clicked.connect(self._on_add_manual_poi)
        buttons.addWidget(self._manual_add_button)
        body.addLayout(buttons)
        return card

    def _load_topics_from_config(self) -> None:
        section = self._config.skills.config_for_skill("topic") or {}
        if not isinstance(section, dict):
            section = {}
        self._topic_section_extras = {
            key: value
            for key, value in section.items()
            if key != "topics"
        }
        try:
            topic_cfg = TopicConfig.model_validate(section)
            self._in_memory_topics = [
                topic.model_copy(deep=True) for topic in topic_cfg.topics
            ]
        except Exception as exc:
            log.warning(f"Failed to load topic config for settings tab: {exc}")
            self._in_memory_topics = []

    def _theme(self):
        return current_theme(self._config)

    def _reload_my_pois_table(self) -> None:
        self._my_pois_table.clearContents()
        self._my_pois_table.setRowCount(len(self._in_memory_topics))

        for row, topic in enumerate(self._in_memory_topics):
            self._my_pois_table.setItem(row, 0, _item(topic.name))
            self._my_pois_table.setItem(row, 1, _item(topic.description))
            self._my_pois_table.setItem(row, 2, _item(", ".join(topic.keywords)))
            self._my_pois_table.setItem(row, 3, _item("\n".join(topic.regex)))
            self._my_pois_table.setItem(
                row,
                4,
                _item("Yes" if topic.llm_judge else "No", align=Qt.AlignmentFlag.AlignCenter),
            )
            self._my_pois_table.setItem(
                row,
                5,
                _item(f"{topic.archive_after_days} days", align=Qt.AlignmentFlag.AlignCenter),
            )

            edit_button = QPushButton("Edit")
            edit_button.clicked.connect(
                lambda _checked=False, index=row: self._on_edit_topic(index)
            )
            self._my_pois_table.setCellWidget(row, 6, edit_button)

            diagnose_button = QPushButton("Diagnose…")
            diagnose_button.clicked.connect(
                lambda _checked=False, index=row: self._on_diagnose_topic(index)
            )
            self._my_pois_table.setCellWidget(row, 7, diagnose_button)

            convert_button = QPushButton("Convert…")
            convert_button.setToolTip(
                "Generate a standalone Skill plugin from this PoI "
                "(removes it from the topic skill)."
            )
            convert_button.clicked.connect(
                lambda _checked=False, index=row: self._on_convert_topic(index)
            )
            self._my_pois_table.setCellWidget(row, 8, convert_button)

            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(
                lambda _checked=False, index=row: self._on_delete_topic(index)
            )
            self._my_pois_table.setCellWidget(row, 9, delete_button)

        self._my_pois_table.resizeRowsToContents()

    def _reload_suggested_table(self) -> None:
        rows = self._pending_candidates()
        self._suggested_table.clearContents()
        self._suggested_table.setRowCount(len(rows))

        for row, candidate in enumerate(rows):
            self._suggested_table.setItem(row, 0, _item(candidate.suggested_name))
            self._suggested_table.setItem(row, 1, _item(candidate.kind, align=Qt.AlignmentFlag.AlignCenter))
            self._suggested_table.setItem(row, 2, _item(f"{candidate.score:.2f}", align=Qt.AlignmentFlag.AlignCenter))
            self._suggested_table.setItem(
                row,
                3,
                _item(_evidence_text(candidate.evidence_capture_ids)),
            )
            self._suggested_table.setItem(
                row,
                4,
                _item(candidate.evidence_quote or ""),
            )

            accept_button = QPushButton("Accept")
            accept_button.clicked.connect(
                lambda _checked=False, candidate_id=candidate.id: self._on_accept_candidate(candidate_id)
            )
            self._suggested_table.setCellWidget(row, 5, accept_button)

            reject_button = QPushButton("Reject")
            reject_button.clicked.connect(
                lambda _checked=False, candidate_id=candidate.id: self._on_reject_candidate(candidate_id)
            )
            self._suggested_table.setCellWidget(row, 6, reject_button)

        self._suggested_table.resizeRowsToContents()

    def _pending_candidates(self) -> list[PoICandidate]:
        with session() as s:
            return list(
                s.scalars(
                    select(PoICandidate)
                    .where(PoICandidate.status == "pending")
                    .order_by(PoICandidate.score.desc(), PoICandidate.id.asc())
                )
            )

    def _sync_discovery_state(self) -> None:
        self._discover_button.setEnabled(not self._discover_busy)
        self._discover_spinner.set_accent(self._theme().accent)
        if self._discover_busy:
            self._discover_spinner.show()
            self._discover_spinner.start()
        else:
            self._discover_spinner.stop()
            self._discover_spinner.hide()

    def _launch_wizard(self) -> None:
        from .poi_wizard import PoIWizard

        wiz = PoIWizard(self._config, parent=self)
        if wiz.exec() == QDialog.DialogCode.Accepted:
            self._load_topics_from_config()
            self._reload_my_pois_table()
            self._reload_suggested_table()
            self.pois_changed.emit()

    def _on_create_from_capture(self) -> None:
        picker = _CapturePickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        capture_id = picker.selected_capture_id()
        if capture_id is None:
            return
        try:
            seed = mine_topic_from_capture(capture_id)
        except Exception as exc:
            log.warning(f"mine_topic_from_capture({capture_id}) failed: {exc}")
            QMessageBox.warning(
                self,
                "Could not seed PoI",
                f"Failed to extract signals from cap-{capture_id}: {exc}",
            )
            return
        if seed is None:
            QMessageBox.warning(
                self,
                "Capture not found",
                f"cap-{capture_id} could not be loaded.",
            )
            return
        self._open_seeded_editor(seed)

    def _open_seeded_editor(self, seed: CaptureSeed) -> None:
        dialog = _TopicEditorDialog(seed.topic, self)
        dialog.setWindowTitle(
            f"New PoI from cap-{seed.capture_id} — review & save"
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_topic = dialog.topic()
        if new_topic is None:
            return
        existing = next(
            (
                topic
                for topic in self._in_memory_topics
                if topic.name.casefold() == new_topic.name.casefold()
            ),
            None,
        )
        if existing is not None:
            QMessageBox.information(
                self,
                "Already tracked",
                f"A PoI named “{new_topic.name}” already exists.",
            )
            return
        self._in_memory_topics.append(new_topic)
        self._reload_my_pois_table()
        self.pois_changed.emit()

    def _on_discover_now(self) -> None:
        if self._discover_busy:
            return
        self._discover_busy = True
        self._discover_status.setText("Scanning the last 14 days…")
        self._sync_discovery_state()
        self._pool.start(
            _DiscoveryTask(self._config.model_copy(deep=True), self._discovery_signals)
        )

    def _on_discovery_done(self, inserted_count: int) -> None:
        self._discover_busy = False
        self._discover_status.setText(
            f"Discovery complete. {inserted_count} new suggestion{'s' if inserted_count != 1 else ''}."
        )
        self._sync_discovery_state()
        self._reload_suggested_table()

    def _on_discovery_failed(self, message: str) -> None:
        self._discover_busy = False
        self._discover_status.setText("Discovery failed.")
        self._sync_discovery_state()
        log.warning(f"PoI discovery failed: {message}")
        QMessageBox.warning(self, "PoI discovery failed", message)

    def _on_add_manual_poi(self) -> None:
        data = self._manual_fields.topic_data()
        if data is None:
            return
        self._in_memory_topics.append(_topic_from_form_data(data))
        self._manual_fields.clear()
        self._reload_my_pois_table()
        self.pois_changed.emit()

    def _on_edit_topic(self, index: int) -> None:
        if index < 0 or index >= len(self._in_memory_topics):
            return
        dialog = _TopicEditorDialog(self._in_memory_topics[index], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.topic()
        if updated is None:
            return
        self._in_memory_topics[index] = updated
        self._reload_my_pois_table()
        self.pois_changed.emit()

    def _on_delete_topic(self, index: int) -> None:
        if index < 0 or index >= len(self._in_memory_topics):
            return
        del self._in_memory_topics[index]
        self._reload_my_pois_table()
        self.pois_changed.emit()

    def _on_diagnose_topic(self, index: int) -> None:
        if index < 0 or index >= len(self._in_memory_topics):
            return
        from ..llm.base import ProviderUnavailable
        from ..llm.factory import make_provider
        from .poi_diagnostic_dialog import PoIDiagnosticDialog

        provider = None
        if self._in_memory_topics[index].llm_judge:
            try:
                provider = make_provider(self._config.llm)
            except ProviderUnavailable:
                provider = None
            except Exception as exc:  # noqa: BLE001 - defensive
                log.warning(f"diagnose: provider construction failed: {exc}")
                provider = None
        dialog = PoIDiagnosticDialog(
            self._in_memory_topics[index],
            provider=provider,
            parent=self,
        )
        dialog.exec()

    def _on_convert_topic(self, index: int) -> None:
        if index < 0 or index >= len(self._in_memory_topics):
            return
        from ..skills.from_topic import convert_topic_to_skill

        topic = self._in_memory_topics[index]
        reply = QMessageBox.question(
            self,
            "Convert PoI to Skill",
            (
                f"Generate a standalone Skill plugin from {topic.name!r}?\n\n"
                "RIN will:\n"
                f"  • Write a new skill.py under your skills folder\n"
                f"  • Remove this PoI from the topic skill\n\n"
                "You'll need to restart RIN and enable the new skill in "
                "Settings → Skills for it to start producing buckets."
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return
        try:
            path = convert_topic_to_skill(topic)
        except FileExistsError as exc:
            overwrite = QMessageBox.question(
                self,
                "Skill already exists",
                f"{exc}\n\nOverwrite the existing file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
            path = convert_topic_to_skill(topic, overwrite=True)
        except Exception as exc:  # noqa: BLE001 - surfaced to user
            log.exception(f"convert_topic_to_skill failed: {exc}")
            QMessageBox.critical(
                self,
                "Conversion failed",
                f"Could not generate skill: {exc}",
            )
            return

        del self._in_memory_topics[index]
        try:
            self.commit_to_config()
            self._config.save()
        except OSError as exc:
            self._in_memory_topics.insert(index, topic)
            log.exception(f"convert_topic_to_skill: could not persist config: {exc}")
            with contextlib.suppress(OSError):
                path.unlink()
                path.parent.rmdir()
            QMessageBox.critical(
                self,
                "Conversion failed",
                (
                    f"Wrote {path} but could not update config: {exc}\n\n"
                    "The generated skill file was removed and the PoI was "
                    "restored. Please try again or check disk space / "
                    "permissions."
                ),
            )
            return

        self._reload_my_pois_table()
        self.pois_changed.emit()
        QMessageBox.information(
            self,
            "Skill generated",
            (
                f"Created {path}\n\n"
                "Restart RIN, then enable the skill in Settings → Skills."
            ),
        )

    def _on_accept_candidate(self, candidate_id: int) -> None:
        with session() as s:
            candidate = s.get(PoICandidate, candidate_id)
            if candidate is None or candidate.status != "pending":
                return
            candidate.status = "accepted"
            candidate.decided_at = datetime.now()
            candidate.decided_by = "user"
            name = candidate.suggested_name
            description = candidate.description or ""

        if not any(topic.name.casefold() == name.casefold() for topic in self._in_memory_topics):
            self._in_memory_topics.append(
                TopicSpec(
                    name=name,
                    description=description,
                    keywords=[name],
                )
            )
            self.pois_changed.emit()
        self._reload_my_pois_table()
        self._reload_suggested_table()

    def _on_reject_candidate(self, candidate_id: int) -> None:
        with session() as s:
            candidate = s.get(PoICandidate, candidate_id)
            if candidate is None or candidate.status != "pending":
                return
            candidate.status = "rejected"
            candidate.decided_at = datetime.now()
            candidate.decided_by = "user"
        self._reload_suggested_table()




def _topic_to_config_row(topic: TopicSpec) -> dict:
    return {
        "name": topic.name,
        "description": topic.description,
        "keywords": list(topic.keywords),
        "regex": list(topic.regex),
        "aliases": list(topic.aliases),
        "llm_judge": topic.llm_judge,
        "archive_after_days": topic.archive_after_days,
        "closed_phrases": list(topic.closed_phrases),
    }


def write_topics_to_config(
    cfg: RinConfig,
    topics: list[TopicSpec],
    *,
    topic_section_extras: dict | None = None,
) -> None:
    raw = dict(cfg.skills.model_dump(mode="python", exclude_none=True))
    raw.update(cfg.skills.model_extra or {})

    raw["topic"] = {
        **(topic_section_extras or {}),
        "topics": [_topic_to_config_row(topic) for topic in topics],
    }

    enabled = list(raw.get("enabled") or [])
    if topics and "topic" not in enabled:
        enabled.append("topic")
    raw["enabled"] = enabled

    cfg.skills = SkillsConfig.model_validate(raw)


def _evidence_text(raw_ids: str) -> str:
    try:
        evidence_ids = json.loads(raw_ids)
    except json.JSONDecodeError:
        evidence_ids = []
    count = len(evidence_ids) if isinstance(evidence_ids, list) else 0
    return f"{count} capture{'s' if count != 1 else ''}"


__all__ = [
    "TopicsAndPoIsTab",
    "write_topics_to_config",
    "_CapturePickerDialog",
    "_TopicEditorDialog",
    "_TopicEditorFields",
    "_TopicFormData",
    "_topic_from_form_data",
]

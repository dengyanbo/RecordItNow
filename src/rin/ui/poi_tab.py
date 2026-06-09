"""Settings UI for the Topics & PoIs page."""
from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ..config import RinConfig, SkillsConfig
from ..poi.discovery import discover, persist_candidates
from ..poi.from_capture import CaptureSeed, mine_topic_from_capture
from ..poi.preview import PreviewResult, preview_matches
from ..skills.builtin.topic.skill import TopicConfig, TopicSpec
from ..storage import session
from ..storage.models import Analysis, Capture, PoICandidate
from ..utils.logging import get_logger
from .progress import Spinner
from .theme import resolve, with_accent

log = get_logger(__name__)

_W_NUMBER = 132
_W_TEXT = 360
_PREVIEW_DEBOUNCE_MS = 300
_PREVIEW_DAYS = 7
_PREVIEW_MAX_EXAMPLES = 3


@dataclass(slots=True)
class _TopicFormData:
    name: str
    description: str
    keywords: list[str]
    regex: list[str]
    llm_judge: bool
    archive_after_days: int
    closed_phrases: list[str]


class _DiscoverySignals(QObject):
    done = Signal(int)
    failed = Signal(str)


class _DiscoveryTask(QRunnable):
    def __init__(self, cfg: RinConfig, signals: _DiscoverySignals) -> None:
        super().__init__()
        self._cfg = cfg
        self._signals = signals

    def run(self) -> None:
        try:
            drafts = discover(self._cfg, days=14)
            inserted_ids = persist_candidates(drafts)
            self._signals.done.emit(len(inserted_ids))
        except Exception as exc:
            self._signals.failed.emit(str(exc))


class _PreviewSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _PreviewTask(QRunnable):
    """Phase 2-A (v0.14.0): runs ``preview_matches`` off the Qt thread."""

    def __init__(
        self,
        signals: _PreviewSignals,
        *,
        regex_patterns: list[str],
        keywords: list[str],
        token: int,
    ) -> None:
        super().__init__()
        self._signals = signals
        self._regex = regex_patterns
        self._keywords = keywords
        self._token = token

    def run(self) -> None:
        try:
            result = preview_matches(
                regex_patterns=self._regex,
                keywords=self._keywords,
                days=_PREVIEW_DAYS,
                max_examples=_PREVIEW_MAX_EXAMPLES,
            )
            self._signals.done.emit((self._token, result))
        except Exception as exc:  # pragma: no cover - defensive worker path
            self._signals.failed.emit(f"{self._token}:{exc}")


class _LivePreviewPanel(QWidget):
    """Renders ``preview_matches`` output below the editor form.

    Hidden by default. ``request_refresh`` schedules a debounced run; the
    panel always reflects the most recently requested input (older
    workers' results are discarded via ``_request_token``).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._signals = _PreviewSignals()
        self._signals.done.connect(
            self._on_done, Qt.ConnectionType.QueuedConnection
        )
        self._signals.failed.connect(
            self._on_failed, Qt.ConnectionType.QueuedConnection
        )

        self._request_token = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_PREVIEW_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._dispatch)

        self._pending_regex: list[str] = []
        self._pending_keywords: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        self._summary = QLabel("")
        self._summary.setProperty("role", "field-label")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._examples_host = QWidget()
        self._examples_layout = QVBoxLayout(self._examples_host)
        self._examples_layout.setContentsMargins(0, 0, 0, 0)
        self._examples_layout.setSpacing(2)
        layout.addWidget(self._examples_host)

        self.hide()

    def request_refresh(
        self, *, regex_patterns: list[str], keywords: list[str]
    ) -> None:
        self._pending_regex = list(regex_patterns)
        self._pending_keywords = list(keywords)
        if not regex_patterns and not keywords:
            self._debounce.stop()
            self._clear_examples()
            self._request_token += 1  # invalidate any in-flight worker
            self._summary.setText("")
            self.hide()
            return
        self._debounce.start()

    def _dispatch(self) -> None:
        self._request_token += 1
        self._summary.setText("Checking the last 7 days…")
        self.show()
        self._clear_examples()
        self._pool.start(
            _PreviewTask(
                self._signals,
                regex_patterns=self._pending_regex,
                keywords=self._pending_keywords,
                token=self._request_token,
            )
        )

    def _on_done(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        token, result = payload
        if token != self._request_token:
            return
        if not isinstance(result, PreviewResult):
            return
        self._clear_examples()
        if result.error:
            self._summary.setText(result.error)
            self.show()
            return
        if result.sampled_captures == 0:
            self._summary.setText(
                "No captures from the last 7 days yet — preview is empty."
            )
            self.show()
            return
        plural = "" if result.matched_count == 1 else "s"
        self._summary.setText(
            f"{result.matched_count} capture{plural} would match "
            f"(scanned {result.sampled_captures})."
        )
        for example in result.examples:
            label = QLabel(
                f"cap-{example.capture_id}: “{example.snippet}”"
            )
            label.setProperty("role", "field-hint")
            label.setWordWrap(True)
            self._examples_layout.addWidget(label)
        self.show()

    def _on_failed(self, message: str) -> None:
        token_str, _, detail = message.partition(":")
        try:
            token = int(token_str)
        except ValueError:
            return
        if token != self._request_token:
            return
        self._clear_examples()
        self._summary.setText("Preview failed.")
        log.warning(f"PoI live preview failed: {detail}")
        self.show()

    def _clear_examples(self) -> None:
        while self._examples_layout.count():
            item = self._examples_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class _TopicEditorFields(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.name_edit = QLineEdit()
        self.name_edit.setFixedWidth(_W_TEXT)

        self.description_edit = QLineEdit()
        self.description_edit.setFixedWidth(_W_TEXT)

        self.keywords_edit = QLineEdit()
        self.keywords_edit.setPlaceholderText("atlas, rollout, customer name")

        self.regex_edit = QPlainTextEdit()
        self.regex_edit.setPlaceholderText(r"One regex per line, e.g. INC\d{7}")
        self.regex_edit.setFixedHeight(76)

        self.llm_judge_check = QCheckBox("Use LLM judge for fuzzy matches")

        self.archive_after_spin = QSpinBox()
        self.archive_after_spin.setRange(1, 3650)
        self.archive_after_spin.setValue(30)
        self.archive_after_spin.setSuffix(" days")
        self.archive_after_spin.setFixedWidth(_W_NUMBER)

        self.closed_phrases_edit = QPlainTextEdit()
        self.closed_phrases_edit.setPlaceholderText("One phrase per line")
        self.closed_phrases_edit.setFixedHeight(76)

        self.error_label = _hint("")
        self.error_label.hide()

        self.preview_panel = _LivePreviewPanel(self)

        form = _form_layout()
        form.addRow(_label("Name"), self.name_edit)
        form.addRow(_label("Description"), self.description_edit)
        form.addRow(_label("Keywords (comma-sep)"), self.keywords_edit)
        form.addRow(_label("Regex (one per line)"), self.regex_edit)
        form.addRow(self.llm_judge_check)
        form.addRow(_label("Archive after N days"), self.archive_after_spin)
        form.addRow(_label("Closed phrases (one per line)"), self.closed_phrases_edit)
        form.addRow(self.error_label)
        form.addRow(self.preview_panel)
        self.setLayout(form)

        self.keywords_edit.textChanged.connect(self._on_pattern_changed)
        self.regex_edit.textChanged.connect(self._on_pattern_changed)
        self._on_pattern_changed()

    def _on_pattern_changed(self) -> None:
        regex = [
            line.strip()
            for line in self.regex_edit.toPlainText().splitlines()
            if line.strip()
        ]
        keywords = [
            part.strip()
            for part in self.keywords_edit.text().split(",")
            if part.strip()
        ]
        self.preview_panel.request_refresh(
            regex_patterns=regex, keywords=keywords
        )

    def load_topic(self, topic: TopicSpec) -> None:
        self.name_edit.setText(topic.name)
        self.description_edit.setText(topic.description)
        self.keywords_edit.setText(", ".join(topic.keywords))
        self.regex_edit.setPlainText("\n".join(topic.regex))
        self.llm_judge_check.setChecked(topic.llm_judge)
        self.archive_after_spin.setValue(topic.archive_after_days)
        self.closed_phrases_edit.setPlainText("\n".join(topic.closed_phrases))
        self.set_error("")

    def clear(self) -> None:
        self.name_edit.clear()
        self.description_edit.clear()
        self.keywords_edit.clear()
        self.regex_edit.clear()
        self.llm_judge_check.setChecked(False)
        self.archive_after_spin.setValue(30)
        self.closed_phrases_edit.clear()
        self.set_error("")

    def topic_data(self) -> _TopicFormData | None:
        name = self.name_edit.text().strip()
        if not name:
            self.set_error("Name is required.")
            return None

        regex = [
            line.strip()
            for line in self.regex_edit.toPlainText().splitlines()
            if line.strip()
        ]
        for pattern in regex:
            try:
                re.compile(pattern)
            except re.error as exc:
                self.set_error(f"Invalid regex {pattern!r}: {exc}")
                return None

        self.set_error("")
        return _TopicFormData(
            name=name,
            description=self.description_edit.text().strip(),
            keywords=[
                part.strip()
                for part in self.keywords_edit.text().split(",")
                if part.strip()
            ],
            regex=regex,
            llm_judge=self.llm_judge_check.isChecked(),
            archive_after_days=self.archive_after_spin.value(),
            closed_phrases=[
                line.strip()
                for line in self.closed_phrases_edit.toPlainText().splitlines()
                if line.strip()
            ],
        )

    def set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))


class _TopicEditorDialog(QDialog):
    def __init__(self, topic: TopicSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit PoI — {topic.name}")
        self._aliases = list(topic.aliases)
        self._topic: TopicSpec | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._fields = _TopicEditorFields(self)
        self._fields.load_topic(topic)
        layout.addWidget(self._fields)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        data = self._fields.topic_data()
        if data is None:
            return
        self._topic = _topic_from_form_data(data, aliases=self._aliases)
        super().accept()

    def topic(self) -> TopicSpec | None:
        return self._topic


class _CapturePickerDialog(QDialog):
    """Phase 2-B: pick a recent capture to seed a new PoI from."""

    _MAX_ROWS = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create PoI from capture")
        self.resize(720, 420)
        self._selected_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = QLabel(
            "Pick a recent capture. RIN will mine its text for the strongest "
            "regex / phrase / domain signal and pre-fill a new PoI editor."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "field-hint")
        layout.addWidget(hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Capture", "When", "Kind", "Summary"])
        _configure_table(self._table)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table, 1)

        self._empty_label = QLabel("No recent captures available.")
        self._empty_label.setProperty("role", "field-hint")
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Use this capture")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_captures()

    def selected_capture_id(self) -> int | None:
        return self._selected_id

    def accept(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        capture_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(capture_id, int):
            return
        self._selected_id = capture_id
        super().accept()

    def _on_double_click(self, _item: QTableWidgetItem) -> None:
        self.accept()

    def _load_captures(self) -> None:
        rows: list[tuple[int, str, datetime, str, str]] = []
        with session() as s:
            captures = list(
                s.scalars(
                    select(Capture)
                    .order_by(Capture.started_at.desc())
                    .limit(self._MAX_ROWS)
                )
            )
            for capture in captures:
                analysis = s.scalar(
                    select(Analysis)
                    .where(Analysis.capture_id == capture.id)
                    .order_by(Analysis.created_at.desc())
                )
                summary = (analysis.summary or "") if analysis else ""
                preview = summary.strip().splitlines()[0] if summary.strip() else ""
                if len(preview) > 140:
                    preview = preview[:137] + "…"
                rows.append(
                    (
                        capture.id,
                        f"cap-{capture.id}",
                        capture.started_at,
                        capture.kind,
                        preview,
                    )
                )

        if not rows:
            self._table.setRowCount(0)
            self._empty_label.show()
            self._ok_button.setEnabled(False)
            return

        self._empty_label.hide()
        self._ok_button.setEnabled(True)
        self._table.setRowCount(len(rows))
        for r, (capture_id, label, started_at, kind, preview) in enumerate(rows):
            id_item = QTableWidgetItem(label)
            id_item.setData(Qt.ItemDataRole.UserRole, capture_id)
            when = started_at.strftime("%Y-%m-%d %H:%M") if started_at else ""
            self._table.setItem(r, 0, id_item)
            self._table.setItem(r, 1, QTableWidgetItem(when))
            self._table.setItem(r, 2, QTableWidgetItem(kind))
            self._table.setItem(r, 3, QTableWidgetItem(preview))
        self._table.selectRow(0)


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
        return with_accent(resolve(self._config.ui.theme), self._config.ui.accent)

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


def _form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)
    form.setContentsMargins(0, 0, 0, 0)
    return form


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "field-label")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "field-hint")
    label.setWordWrap(True)
    return label


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(10)

    heading = QLabel(title)
    heading.setProperty("heading", "h2")
    layout.addWidget(heading)
    return card, layout


def _configure_table(table: QTableWidget) -> None:
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setMinimumHeight(180)


def _item(text: str, *, align: Qt.AlignmentFlag | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if align is not None:
        item.setTextAlignment(align)
    return item


def _topic_from_form_data(
    data: _TopicFormData,
    *,
    aliases: list[str] | None = None,
) -> TopicSpec:
    return TopicSpec(
        name=data.name,
        description=data.description,
        keywords=list(data.keywords),
        regex=list(data.regex),
        aliases=list(aliases or []),
        llm_judge=data.llm_judge,
        archive_after_days=data.archive_after_days,
        closed_phrases=list(data.closed_phrases),
    )


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


__all__ = ["TopicsAndPoIsTab", "write_topics_to_config"]

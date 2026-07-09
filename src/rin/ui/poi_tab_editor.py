"""Topic editor dialog and live preview panel for the Topics & PoIs settings UI."""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..poi.preview import PreviewResult, preview_matches
from ..skills.builtin.topic.skill import TopicSpec
from ..utils.logging import get_logger
from .poi_tab_widgets import _form_layout, _hint, _label

log = get_logger("rin.ui.poi_tab")

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



__all__ = [
    "_TopicEditorDialog",
    "_TopicEditorFields",
    "_TopicFormData",
    "_topic_from_form_data",
]

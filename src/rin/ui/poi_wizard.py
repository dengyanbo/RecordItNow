"""First Points-of-Interest setup wizard."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)
from sqlalchemy import select

from ..config import RinConfig
from ..poi import discovery as poi_discovery
from ..skills.builtin.topic.skill import TopicConfig, TopicSpec
from ..storage import session
from ..storage.models import PoICandidate
from ..utils.logging import get_logger
from .icon import tinted_icon
from .poi_tab import write_topics_to_config
from .progress import Spinner
from .style import palette_to_qss
from .theme import resolve, with_accent

log = get_logger(__name__)


class _DiscoverySignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _DiscoveryTask(QRunnable):
    def __init__(self, cfg: RinConfig, signals: _DiscoverySignals) -> None:
        super().__init__()
        self._cfg = cfg
        self._signals = signals

    def run(self) -> None:
        try:
            drafts = poi_discovery.discover(self._cfg, days=14, use_llm=False)
            self._signals.done.emit(drafts)
        except Exception as exc:  # pragma: no cover - defensive worker path
            self._signals.failed.emit(str(exc))


class _HeaderPage(QWizardPage):
    def __init__(self, *, icon_name: str, accent: str, title: str, body: str) -> None:
        super().__init__()
        self.setTitle("")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(16)
        outer.addWidget(_header(icon_name, accent, title, body))
        self._body_layout = QVBoxLayout()
        self._body_layout.setSpacing(12)
        outer.addLayout(self._body_layout)
        outer.addStretch(1)


class _WelcomePage(_HeaderPage):
    def __init__(self, accent: str) -> None:
        super().__init__(
            icon_name="lightbulb",
            accent=accent,
            title="Set up Topics & Points of Interest",
            body=(
                "RIN can group captures around the topics you care about: projects, customers, papers, "
                "or ticket IDs. This wizard can suggest some PoIs from recent work, or you can declare "
                "them yourself. You can skip and come back later from Settings."
            ),
        )


class _ManualInputRow(QWidget):
    def __init__(self, on_add) -> None:
        super().__init__()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Description (optional)")
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(lambda: on_add(self))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.name_edit, 2)
        layout.addWidget(self.description_edit, 3)
        layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)


class _ManualPage(_HeaderPage):
    def __init__(self, accent: str) -> None:
        super().__init__(
            icon_name="info",
            accent=accent,
            title="Tell me what to track",
            body="Add up to three Points of Interest now, or leave this blank and let discovery suggest some next.",
        )
        self._added_topics: list[TopicSpec] = []

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        added_label = QLabel("Already added")
        added_label.setProperty("role", "field-label")
        card_layout.addWidget(added_label)

        self._added_list = QVBoxLayout()
        self._added_list.setContentsMargins(0, 0, 0, 0)
        self._added_list.setSpacing(6)
        card_layout.addLayout(self._added_list)

        self._rows = [_ManualInputRow(self._on_add_clicked) for _ in range(3)]
        for row in self._rows:
            card_layout.addWidget(row)

        self._status = QLabel("")
        self._status.setProperty("role", "field-hint")
        self._status.setWordWrap(True)
        self._status.hide()
        card_layout.addWidget(self._status)

        self._body_layout.addWidget(card)

        footer = QLabel("Or skip — discovery on the next page might find them automatically.")
        footer.setProperty("role", "field-hint")
        footer.setWordWrap(True)
        self._body_layout.addWidget(footer)

        self._render_added_topics()

    def added_topics(self) -> list[TopicSpec]:
        return [topic.model_copy(deep=True) for topic in self._added_topics]

    def _on_add_clicked(self, row: _ManualInputRow) -> None:
        name = row.name_edit.text().strip()
        description = row.description_edit.text().strip()
        if not name:
            self._status.setText("Enter a name before adding a PoI.")
            self._status.show()
            return
        if len(self._added_topics) >= 3:
            self._status.setText("You can add up to three PoIs in this wizard.")
            self._status.show()
            return
        key = name.casefold()
        if any(topic.name.casefold() == key for topic in self._added_topics):
            self._status.setText("That PoI is already in the list.")
            self._status.show()
            return

        self._added_topics.append(
            TopicSpec(
                name=name,
                description=description,
                keywords=[name],
            )
        )
        row.name_edit.clear()
        row.description_edit.clear()
        self._status.hide()
        self._render_added_topics()

    def _remove_topic(self, index: int) -> None:
        if 0 <= index < len(self._added_topics):
            del self._added_topics[index]
            self._status.hide()
            self._render_added_topics()

    def _render_added_topics(self) -> None:
        while self._added_list.count():
            item = self._added_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._added_topics:
            empty = QLabel("No PoIs added yet.")
            empty.setProperty("role", "field-hint")
            self._added_list.addWidget(empty)
        else:
            for index, topic in enumerate(self._added_topics):
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(8)
                label = QLabel(topic.name if not topic.description else f"{topic.name} — {topic.description}")
                label.setWordWrap(True)
                remove_btn = QPushButton("Remove")
                remove_btn.setProperty("flat", True)
                remove_btn.setFlat(True)
                remove_btn.clicked.connect(lambda _checked=False, i=index: self._remove_topic(i))
                layout.addWidget(label, 1)
                layout.addWidget(remove_btn, 0, Qt.AlignmentFlag.AlignRight)
                self._added_list.addWidget(row)

        full = len(self._added_topics) >= 3
        for row in self._rows:
            row.add_button.setEnabled(not full)


class _DiscoveryPage(_HeaderPage):
    def __init__(self, cfg: RinConfig, accent: str) -> None:
        super().__init__(
            icon_name="search",
            accent=accent,
            title="Topics RIN noticed",
            body="RIN can scan your recent captures for recurring projects, customers, and identifiers.",
        )
        self._cfg = cfg
        self._pool = QThreadPool.globalInstance()
        self._signals = _DiscoverySignals()
        self._signals.done.connect(self._on_discovery_done, Qt.ConnectionType.QueuedConnection)
        self._signals.failed.connect(self._on_discovery_failed, Qt.ConnectionType.QueuedConnection)

        self._started = False
        self._running = False
        self._ready = False
        self._skipped = False
        self._drafts: list[poi_discovery.PoICandidateDraft] = []
        self._checks: list[tuple[poi_discovery.PoICandidateDraft, QCheckBox]] = []

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        busy_row = QHBoxLayout()
        busy_row.setContentsMargins(0, 0, 0, 0)
        busy_row.setSpacing(8)
        self._spinner = Spinner(size=18, accent=accent)
        busy_row.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        self._status = QLabel("Looking through your recent captures…")
        self._status.setProperty("role", "field-hint")
        self._status.setWordWrap(True)
        busy_row.addWidget(self._status, 1)
        card_layout.addLayout(busy_row)

        self._results_host = QWidget()
        self._results_layout = QVBoxLayout(self._results_host)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(8)
        card_layout.addWidget(self._results_host)

        skip_row = QHBoxLayout()
        skip_row.setContentsMargins(0, 0, 0, 0)
        skip_row.addStretch(1)
        self._skip_button = QPushButton("Skip discovery")
        self._skip_button.setProperty("flat", True)
        self._skip_button.setFlat(True)
        self._skip_button.clicked.connect(self._on_skip_clicked)
        skip_row.addWidget(self._skip_button)
        card_layout.addLayout(skip_row)

        self._body_layout.addWidget(card)
        self._set_busy(True)

    def initializePage(self) -> None:
        super().initializePage()
        self._ensure_started()

    def isComplete(self) -> bool:
        return self._ready and not self._running

    def accepted_drafts(self) -> list[poi_discovery.PoICandidateDraft]:
        if self._skipped:
            return []
        return [draft for draft, checkbox in self._checks if checkbox.isChecked()]

    def _ensure_started(self) -> None:
        if self._started or self._skipped:
            return
        self._started = True
        self._running = True
        self._ready = False
        self._set_busy(True)
        self._start_task(_DiscoveryTask(self._cfg.model_copy(deep=True), self._signals))

    def _start_task(self, task: QRunnable) -> None:
        self._pool.start(task)

    def _on_skip_clicked(self) -> None:
        self._skipped = True
        self._running = False
        self._ready = True
        self._drafts = []
        self._checks = []
        self._set_busy(False)
        self._clear_results()
        self._status.setText("Discovery skipped.")
        self.completeChanged.emit()
        wizard = self.wizard()
        if isinstance(wizard, QWizard):
            wizard.next()

    def _on_discovery_done(self, drafts: object) -> None:
        if self._skipped:
            return
        self._running = False
        self._ready = True
        self._drafts = list(drafts)[:10]
        self._checks = []
        self._set_busy(False)
        self._clear_results()

        if not self._drafts:
            self._status.setText(
                "No suggestions yet — that's OK. RIN will offer more as you use it."
            )
            self.completeChanged.emit()
            return

        self._status.setText("Select any suggestions you want to keep.")
        for draft in self._drafts:
            checkbox = QCheckBox(draft.suggested_name)
            checkbox.setChecked(True)
            meta = QLabel(
                f"(seen in {len(draft.evidence_capture_ids)} capture{'s' if len(draft.evidence_capture_ids) != 1 else ''})"
            )
            meta.setProperty("role", "field-hint")
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addWidget(checkbox)
            layout.addWidget(meta)
            layout.addStretch(1)
            self._results_layout.addWidget(row)
            self._checks.append((draft, checkbox))
        self._results_layout.addStretch(1)
        self.completeChanged.emit()

    def _on_discovery_failed(self, message: str) -> None:
        if self._skipped:
            return
        self._running = False
        self._ready = True
        self._drafts = []
        self._checks = []
        self._set_busy(False)
        self._clear_results()
        self._status.setText("No suggestions yet — that's OK. RIN will offer more as you use it.")
        log.warning(f"PoI wizard discovery failed: {message}")
        self.completeChanged.emit()

    def _clear_results(self) -> None:
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_busy(self, running: bool) -> None:
        self._spinner.setVisible(running)
        if running:
            self._spinner.start()
        else:
            self._spinner.stop()


class _ConfirmPage(_HeaderPage):
    def __init__(self, accent: str) -> None:
        super().__init__(
            icon_name="checkmark",
            accent=accent,
            title="Ready to go",
            body="Review the Points of Interest RIN will track after this wizard.",
        )
        self.setFinalPage(True)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setProperty("role", "field-hint")
        self._body_layout.addWidget(self._summary)

    def initializePage(self) -> None:
        wizard = self.wizard()
        assert isinstance(wizard, PoIWizard)
        topics = wizard.final_topics()
        if topics:
            names = ", ".join(topic.name for topic in topics)
            self._summary.setText(f"You'll track these {len(topics)} PoIs: {names}")
        else:
            self._summary.setText(
                "No PoIs configured. You can add some anytime from Settings → Topics & PoIs."
            )
        super().initializePage()


class PoIWizard(QWizard):
    def __init__(self, cfg: RinConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = cfg
        self.setWindowTitle("Set up Topics & Points of Interest")
        self.setMinimumSize(720, 520)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoCancelButton, True)

        theme = with_accent(resolve(cfg.ui.theme), cfg.ui.accent)
        self.setStyleSheet(palette_to_qss(theme, density=cfg.ui.density))
        self._accent = theme.accent

        self._welcome_page = _WelcomePage(self._accent)
        self._manual_page = _ManualPage(self._accent)
        self._discovery_page = _DiscoveryPage(cfg, self._accent)
        self._confirm_page = _ConfirmPage(self._accent)

        self.setPage(0, self._welcome_page)
        self.setPage(1, self._manual_page)
        self.setPage(2, self._discovery_page)
        self.setPage(3, self._confirm_page)
        self.setStartId(0)
        self.setButtonText(QWizard.WizardButton.NextButton, "Continue")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Finish")

    def final_topics(self) -> list[TopicSpec]:
        existing, _extras = self._load_existing_topic_config()
        return _merge_topics(
            existing,
            self._manual_page.added_topics(),
            [_draft_to_topic(draft) for draft in self._discovery_page.accepted_drafts()],
        )

    def accept(self) -> None:
        topics, extras = self._load_existing_topic_config()
        merged_topics = _merge_topics(
            topics,
            self._manual_page.added_topics(),
            [_draft_to_topic(draft) for draft in self._discovery_page.accepted_drafts()],
        )
        write_topics_to_config(
            self._config,
            merged_topics,
            topic_section_extras=extras,
        )

        accepted_names = {
            draft.suggested_name.casefold()
            for draft in self._discovery_page.accepted_drafts()
            if draft.suggested_name.strip()
        }
        if accepted_names:
            now = datetime.now()
            with session() as s:
                rows = [
                    row
                    for row in s.scalars(
                        select(PoICandidate).where(PoICandidate.status == "pending")
                    )
                    if row.suggested_name.casefold() in accepted_names
                ]
                for row in rows:
                    row.status = "accepted"
                    row.decided_at = now
                    row.decided_by = "user"

        self._config.skills.poi_wizard_seen = True
        self._config.save()
        log.info("PoI wizard completed")
        super().accept()

    def _load_existing_topic_config(self) -> tuple[list[TopicSpec], dict]:
        section = self._config.skills.config_for_skill("topic") or {}
        if not isinstance(section, dict):
            section = {}
        extras = {key: value for key, value in section.items() if key != "topics"}
        try:
            topic_cfg = TopicConfig.model_validate(section)
            topics = [topic.model_copy(deep=True) for topic in topic_cfg.topics]
        except Exception as exc:
            log.warning(f"Failed to load topic config for PoI wizard: {exc}")
            topics = []
        return topics, extras


def _header(icon_name: str, accent: str, title: str, body: str) -> QWidget:
    widget = QWidget()
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(tinted_icon(icon_name, accent, sizes=(32,)).pixmap(QSize(32, 32)))
    icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
    row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(6)
    heading = QLabel(title)
    heading.setProperty("heading", "h1")
    body_label = QLabel(body)
    body_label.setProperty("role", "caption")
    body_label.setWordWrap(True)
    text_col.addWidget(heading)
    text_col.addWidget(body_label)
    row.addLayout(text_col, 1)
    return widget


def _draft_to_topic(draft: poi_discovery.PoICandidateDraft) -> TopicSpec:
    return TopicSpec(
        name=draft.suggested_name,
        description=draft.description or "",
        keywords=[draft.suggested_name],
    )


def _merge_topics(*groups: list[TopicSpec]) -> list[TopicSpec]:
    merged: list[TopicSpec] = []
    seen: set[str] = set()
    for group in groups:
        for topic in group:
            key = topic.name.strip().casefold()
            if not key or key in seen:
                continue
            merged.append(topic.model_copy(deep=True))
            seen.add(key)
    return merged


__all__ = ["PoIWizard"]

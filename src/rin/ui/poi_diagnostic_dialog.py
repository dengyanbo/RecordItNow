"""Phase 2-C (v0.16.0): "Why didn't this match?" diagnostic dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..llm.base import Provider
from ..poi.diagnostic import (
    DiagnosticResult,
    DiagnosticStep,
    diagnose_topic_against_capture,
)
from ..skills.builtin.topic.skill import TopicSpec
from .poi_tab import _CapturePickerDialog


class PoIDiagnosticDialog(QDialog):
    """Run a topic against a user-picked capture and show per-step verdicts."""

    def __init__(
        self,
        topic: TopicSpec,
        *,
        provider: Provider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Why didn't this match? — {topic.name}")
        self.resize(620, 520)
        self._topic = topic
        self._provider = provider
        self._result: DiagnosticResult | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        header = QLabel(
            f"Topic: <b>{topic.name}</b><br>"
            "Pick a capture, then RIN will run each match layer in order."
        )
        header.setWordWrap(True)
        outer.addWidget(header)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self._pick_button = QPushButton("Pick capture…")
        self._pick_button.clicked.connect(self._on_pick_capture)
        actions.addWidget(self._pick_button)
        self._capture_label = QLabel("No capture selected.")
        self._capture_label.setWordWrap(True)
        self._capture_label.setProperty("role", "field-hint")
        actions.addWidget(self._capture_label, 1)
        outer.addLayout(actions)

        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("font-weight: 600;")
        outer.addWidget(self._summary_label)

        self._steps_host = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_host)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(6)
        self._steps_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._steps_host)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def result(self) -> DiagnosticResult | None:
        return self._result

    def run_against_capture(self, capture_id: int) -> None:
        """Programmatic entry point (also used by tests)."""

        result = diagnose_topic_against_capture(
            self._topic, capture_id, provider=self._provider
        )
        self._result = result
        if result is None:
            self._capture_label.setText(f"cap-{capture_id} not found.")
            self._render_steps([])
            return
        self._capture_label.setText(
            f"cap-{capture_id} · {result.capture_text_chars:,} chars · "
            f"{result.summary_preview or '(no summary)'}"
        )
        verdict = "MATCH ✅" if result.overall_match else "NO MATCH ❌"
        self._summary_label.setText(
            f"Overall: {verdict} (any layer passes counts as a match)"
        )
        self._render_steps(result.steps)

    def _on_pick_capture(self) -> None:
        picker = _CapturePickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        capture_id = picker.selected_capture_id()
        if capture_id is None:
            return
        self.run_against_capture(capture_id)

    def _render_steps(self, steps: list[DiagnosticStep]) -> None:
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not steps:
            empty = QLabel("No diagnostic steps yet — pick a capture above.")
            empty.setProperty("role", "field-hint")
            self._steps_layout.addWidget(empty)
            self._steps_layout.addStretch(1)
            return
        for step in steps:
            self._steps_layout.addWidget(_StepRow(step))
        self._steps_layout.addStretch(1)


class _StepRow(QWidget):
    def __init__(self, step: DiagnosticStep) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        icon = "✅" if step.passed else "❌"
        title = QLabel(f"{icon}  {step.kind} · {step.value}")
        title.setStyleSheet("font-weight: 600;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title)

        if step.matched_text:
            matched = QLabel(f"matched: {step.matched_text}")
            matched.setWordWrap(True)
            matched.setStyleSheet("color: palette(text);")
            matched.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(matched)
        if step.closest_text:
            closest = QLabel(f"closest: {step.closest_text}")
            closest.setWordWrap(True)
            closest.setStyleSheet("color: palette(mid);")
            closest.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(closest)
        if step.notes:
            notes = QLabel(step.notes)
            notes.setWordWrap(True)
            notes.setProperty("role", "field-hint")
            layout.addWidget(notes)


__all__ = ["PoIDiagnosticDialog"]

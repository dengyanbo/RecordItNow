"""Phase 2-C (v0.16.0): conversational PoI intake dialog."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..llm.base import Provider
from ..poi.conversational import ChatState, synth_topic_spec_from_chat
from ..skills.builtin.topic.skill import TopicSpec


class PoIChatDialog(QDialog):
    """4-turn conversational intake that returns a :class:`TopicSpec`.

    The dialog walks the user through the canned questions in
    :mod:`rin.poi.conversational`, accumulates answers, and on Finish
    synthesizes a TopicSpec (LLM-assisted when ``provider`` is given,
    heuristic otherwise). "Skip" exits early and returns whatever
    answers were given so far — or ``None`` if nothing was answered.
    """

    def __init__(
        self,
        *,
        provider: Provider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Describe a new PoI with chat")
        self.resize(560, 480)
        self._provider = provider
        self._state = ChatState()
        self._result: TopicSpec | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        intro = QLabel(
            "Answer these 4 short questions to set up a Point of Interest. "
            "RIN will assemble a starter `topic` config for you to review."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "field-hint")
        outer.addWidget(intro)

        self._history_host = QWidget()
        self._history_layout = QVBoxLayout(self._history_host)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(8)
        self._history_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._history_host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self._question_label = QLabel("")
        self._question_label.setWordWrap(True)
        self._question_label.setStyleSheet("font-weight: 600;")
        outer.addWidget(self._question_label)

        self._answer_edit = QPlainTextEdit()
        self._answer_edit.setPlaceholderText("Type your answer here…")
        self._answer_edit.setFixedHeight(80)
        outer.addWidget(self._answer_edit)

        button_row = QDialogButtonBox()
        self._next_button = QPushButton("Next →")
        self._next_button.setDefault(True)
        self._next_button.clicked.connect(self._on_next)
        button_row.addButton(self._next_button, QDialogButtonBox.ButtonRole.AcceptRole)

        self._finish_button = QPushButton("Finish & build PoI")
        self._finish_button.clicked.connect(self._on_finish)
        button_row.addButton(self._finish_button, QDialogButtonBox.ButtonRole.AcceptRole)

        self._skip_button = QPushButton("Skip / use manual form")
        self._skip_button.clicked.connect(self._on_skip)
        button_row.addButton(self._skip_button, QDialogButtonBox.ButtonRole.RejectRole)

        outer.addWidget(button_row)

        self._render()

    def topic(self) -> TopicSpec | None:
        return self._result

    def _on_next(self) -> None:
        text = self._answer_edit.toPlainText().strip()
        # Allow empty answers for optional questions (anti, closed).
        self._state.answer(text)
        self._answer_edit.clear()
        if self._state.is_done:
            self._on_finish()
        else:
            self._render()

    def _on_finish(self) -> None:
        # Capture whatever's currently in the box first.
        text = self._answer_edit.toPlainText().strip()
        if text and not self._state.is_done:
            self._state.answer(text)
            self._answer_edit.clear()
        spec = synth_topic_spec_from_chat(self._state, provider=self._provider)
        if spec is None:
            # Nothing to build from; behave like Skip.
            self._on_skip()
            return
        self._result = spec
        self.accept()

    def _on_skip(self) -> None:
        self._state.skip()
        self._result = None
        self.reject()

    def _render(self) -> None:
        # Wipe + rebuild the history view.
        while self._history_layout.count():
            item = self._history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for turn in self._state.turns:
            if not turn.answer:
                continue
            q = QLabel(f"🟪 {turn.question}")
            q.setWordWrap(True)
            q.setStyleSheet("color: palette(mid);")
            self._history_layout.addWidget(q)
            a = QLabel(f"🟦 {turn.answer}")
            a.setWordWrap(True)
            self._history_layout.addWidget(a)

        self._history_layout.addStretch(1)

        idx = self._state.current_index
        if idx < len(self._state.turns):
            self._question_label.setText(self._state.turns[idx].question)
            self._answer_edit.setEnabled(True)
            self._next_button.setEnabled(True)
            self._finish_button.setEnabled(idx > 0)
        else:
            self._question_label.setText("All set — click 'Finish & build PoI'.")
            self._answer_edit.setEnabled(False)
            self._next_button.setEnabled(False)
            self._finish_button.setEnabled(True)


__all__ = ["PoIChatDialog"]

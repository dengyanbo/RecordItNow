"""Search & Ask — one unified ChatGPT/Gemini-style conversation (v1.1.0).

A single scrollable conversation thread plus one input bar. A
``Search | Ask`` segmented toggle next to the input decides what happens
when the user submits:

* **Search** runs semantic capture search and renders a left-aligned
  "results" message containing the matching capture cards.
* **Ask** runs the RAG agent and renders a left-aligned agent bubble with
  ``cap-N`` citations.

Both kinds of turn share the same thread, so search results and answers
interleave with the user's queries. The active mode is remembered in
``config.search_mode`` and restored next time the window opens.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import RinConfig
from ..rag.agent import Answer, RAGAgent
from ..rag.search import SearchHit, search
from ..utils.logging import get_logger
from .icon import tinted_icon
from .progress import Spinner
from .theme import LIGHT, resolve, with_accent

log = get_logger(__name__)


class _SearchEmptyState(QWidget):
    """Centered placeholder shown before the first message, with icon."""

    def __init__(
        self,
        title: str,
        hint: str,
        *,
        icon_name: str = "search",
        icon_color: str = "#9E9E9E",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(8)
        layout.addStretch()

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setPixmap(
            tinted_icon(icon_name, icon_color, sizes=(40,)).pixmap(QSize(40, 40))
        )
        layout.addWidget(self._icon_label)

        self._title = QLabel(title)
        self._title.setProperty("role", "empty-state-title")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint = QLabel(hint)
        self._hint.setProperty("role", "empty-state-hint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setMinimumHeight(48)
        layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._hint)
        layout.addStretch()

    def set_text(self, title: str, hint: str) -> None:
        self._title.setText(title)
        self._hint.setText(hint)


class _WorkerSignals(QObject):
    search_done = Signal(list)
    answer_done = Signal(object)
    error = Signal(str)


class _SearchTask(QRunnable):
    def __init__(self, query: str, signals: _WorkerSignals) -> None:
        super().__init__()
        self._query = query
        self._signals = signals

    def run(self) -> None:  # pragma: no cover
        try:
            self._signals.search_done.emit(search(self._query, k=8))
        except Exception as exc:
            self._signals.error.emit(str(exc))


class _AskTask(QRunnable):
    def __init__(self, agent: RAGAgent, question: str, signals: _WorkerSignals) -> None:
        super().__init__()
        self._agent = agent
        self._question = question
        self._signals = signals

    def run(self) -> None:  # pragma: no cover
        try:
            self._signals.answer_done.emit(self._agent.ask(self._question))
        except Exception as exc:
            self._signals.error.emit(str(exc))


def _result_card(hit: SearchHit) -> QWidget:
    card = QFrame()
    card.setObjectName("card")
    when = hit.started_at.strftime("%b %d, %Y · %H:%M") if hit.started_at else "—"
    head = QLabel(f"cap-{hit.capture_id}")
    head.setStyleSheet("font-weight: 600;")
    timestamp = QLabel(when)
    timestamp.setProperty("muted", True)
    score = QLabel(f"score {hit.score:.2f}")
    score.setProperty("role", "chip")
    snippet = QLabel(hit.snippet[:240])
    snippet.setWordWrap(True)
    snippet.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    top = QHBoxLayout()
    top.setSpacing(8)
    top.addWidget(head, 0, Qt.AlignmentFlag.AlignVCenter)
    top.addWidget(timestamp, 0, Qt.AlignmentFlag.AlignVCenter)
    top.addStretch()
    top.addWidget(score, 0, Qt.AlignmentFlag.AlignVCenter)
    col = QVBoxLayout(card)
    col.setContentsMargins(14, 12, 14, 12)
    col.setSpacing(6)
    col.addLayout(top)
    col.addWidget(snippet)
    return card


def _results_message(hits: list[SearchHit]) -> QWidget:
    """Left-aligned conversation turn holding the search result cards."""

    container = QWidget()
    col = QVBoxLayout(container)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(8)
    if not hits:
        empty = QLabel("No matches — try different wording.")
        empty.setProperty("role", "empty-state-hint")
        empty.setWordWrap(True)
        col.addWidget(empty)
    else:
        header = QLabel(f"Found {len(hits)} capture{'s' if len(hits) != 1 else ''}")
        header.setProperty("role", "caption")
        col.addWidget(header)
        for h in hits:
            col.addWidget(_result_card(h))
    container.setMaximumWidth(620)

    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(container, 0)
    row.addStretch()
    return wrapper


def _chat_bubble(text: str, role: str, citations: list[SearchHit] | None = None) -> QWidget:
    """Build a chat bubble: ``role`` is "user" or "agent"."""

    bubble = QFrame()
    bubble.setObjectName("card")
    bubble.setProperty("role", "user-bubble" if role == "user" else "agent-bubble")
    inner = QVBoxLayout(bubble)
    inner.setContentsMargins(14, 10, 14, 10)
    inner.setSpacing(4)

    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    inner.addWidget(label)
    if citations:
        cite_row = QHBoxLayout()
        cite_row.setContentsMargins(0, 4, 0, 0)
        cite_row.setSpacing(4)
        for h in citations[:6]:
            chip = QLabel(f"cap-{h.capture_id}")
            chip.setProperty("role", "chip")
            chip.setProperty("accent", True)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cite_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        cite_row.addStretch()
        wrap = QWidget()
        wrap.setLayout(cite_row)
        inner.addWidget(wrap)

    # Wrap in a horizontal layout so we can right-align user / left-align agent.
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    if role == "user":
        row.addStretch()
        row.addWidget(bubble, 0)
    else:
        row.addWidget(bubble, 0)
        row.addStretch()
    bubble.setMaximumWidth(560)
    return wrapper


class _ModeToggle(QWidget):
    """Segmented ``Search | Ask`` control. Emits the chosen mode on click."""

    mode_changed = Signal(str)  # "search" | "ask"

    def __init__(
        self,
        initial: str = "ask",
        *,
        ask_enabled: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._search_btn = QPushButton("Search")
        self._ask_btn = QPushButton("Ask")
        for btn, pos in ((self._search_btn, "left"), (self._ask_btn, "right")):
            btn.setCheckable(True)
            btn.setProperty("role", "segment")
            btn.setProperty("segment-pos", pos)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self._search_btn)
        group.addButton(self._ask_btn)

        self._ask_btn.setEnabled(ask_enabled)
        if initial == "ask" and ask_enabled:
            self._ask_btn.setChecked(True)
        else:
            self._search_btn.setChecked(True)

        # ``clicked`` only fires on user interaction, not on the programmatic
        # setChecked above — so opening the window never re-persists the mode.
        self._search_btn.clicked.connect(lambda: self.mode_changed.emit("search"))
        self._ask_btn.clicked.connect(lambda: self.mode_changed.emit("ask"))

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._search_btn)
        row.addWidget(self._ask_btn)

    def mode(self) -> str:
        return "search" if self._search_btn.isChecked() else "ask"

    def set_mode(self, mode: str) -> None:
        (self._search_btn if mode == "search" else self._ask_btn).setChecked(True)


class SearchWindow(QWidget):
    def __init__(self, config: RinConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._agent = RAGAgent.from_config(config)
        self._pool = QThreadPool.globalInstance()
        self._signals = _WorkerSignals()
        self._signals.search_done.connect(self._on_search_done)
        self._signals.answer_done.connect(self._on_answer_done)
        self._signals.error.connect(self._on_error)

        self.setWindowTitle("RIN — Search & Ask")
        self.resize(860, 760)

        # Restore the persisted mode; force Search when no provider is available.
        self._mode = getattr(config, "search_mode", "ask")
        if self._agent is None:
            self._mode = "search"

        # --- conversation thread ----------------------------------------------
        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(0, 0, 8, 0)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch()

        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_scroll.setWidget(self._chat_container)

        self._empty = _SearchEmptyState(
            "Search your captures or ask a question",
            "Pick Search to find captures by meaning, or Ask to get answers with "
            "citations. Type below and press Enter.",
            icon_name="search",
        )
        self._stack = QStackedWidget()
        self._stack.addWidget(self._empty)        # index 0
        self._stack.addWidget(self._chat_scroll)  # index 1

        # --- input bar --------------------------------------------------------
        self._toggle = _ModeToggle(self._mode, ask_enabled=self._agent is not None)
        self._toggle.mode_changed.connect(self._on_mode_changed)

        self._input = QLineEdit()
        self._input.setProperty("role", "search")
        self._input.returnPressed.connect(self._submit)
        self._submit_btn = QPushButton()
        self._submit_btn.setProperty("primary", True)
        self._submit_btn.setProperty("role", "search-attached")
        self._submit_btn.clicked.connect(self._submit)

        attached = QHBoxLayout()
        attached.setSpacing(0)
        attached.addWidget(self._input, 1)
        attached.addWidget(self._submit_btn, 0)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_row.addWidget(self._toggle, 0)
        input_row.addLayout(attached, 1)

        # --- assemble ---------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        heading = QLabel("Search & Ask")
        heading.setProperty("heading", "h1")
        layout.addWidget(heading)
        sub = QLabel(
            "One place to search your captures semantically or ask the RAG agent "
            "— pick a mode and type below."
        )
        sub.setProperty("role", "caption")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(12)
        layout.addWidget(self._stack, 1)
        layout.addSpacing(8)
        layout.addLayout(input_row)

        self._sync_mode_ui()

    def _theme(self):
        try:
            return with_accent(resolve(self.config.ui.theme), self.config.ui.accent)
        except Exception:
            return LIGHT

    # --- mode -----------------------------------------------------------------

    def _sync_mode_ui(self) -> None:
        """Adapt the placeholder + submit button to the active mode."""

        if self._mode == "search":
            self._input.setPlaceholderText("Search captures semantically…")
            self._submit_btn.setText("Search")
        else:
            self._input.setPlaceholderText(
                "Ask anything (e.g. 'what was that error I saw on Tuesday?')"
            )
            self._submit_btn.setText("Send")

    def _on_mode_changed(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._sync_mode_ui()
        # Persist the choice so the window reopens in the same mode.
        try:
            self.config.search_mode = mode
            self.config.save()
        except Exception as exc:  # pragma: no cover - best effort
            log.warning(f"Could not persist search_mode: {exc}")
        self._input.setFocus()

    # --- submit / slots -------------------------------------------------------

    def _submit(self) -> None:
        q = self._input.text().strip()
        if not q:
            return
        self._stack.setCurrentIndex(1)
        self._add_chat_bubble(q, role="user")
        self._input.clear()

        if self._mode == "search":
            self._add_thinking_bubble("Searching captures…")
            self._pool.start(_SearchTask(q, self._signals))
            return

        if self._agent is None:
            self._add_chat_bubble(
                "Q&A is disabled — no LLM provider is configured. Switch to "
                "Search, or pick a provider in Settings → Analysis.",
                role="agent",
            )
            return
        self._add_thinking_bubble("Thinking…")
        self._pool.start(_AskTask(self._agent, q, self._signals))

    def _on_search_done(self, hits: list[SearchHit]) -> None:
        self._remove_last_widget()
        message = _results_message(hits)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, message)
        self._scroll_to_bottom()

    def _on_answer_done(self, answer: Answer) -> None:
        self._remove_last_widget()
        self._add_chat_bubble(answer.text, role="agent", citations=answer.hits)

    def _on_error(self, msg: str) -> None:
        log.error(f"Search window error: {msg}")
        self._remove_last_widget()
        self._add_chat_bubble(f"Error: {msg}", role="agent")

    # --- thread helpers -------------------------------------------------------

    def _add_chat_bubble(
        self, text: str, *, role: str, citations: list[SearchHit] | None = None
    ) -> None:
        bubble = _chat_bubble(text, role, citations)
        # Insert before the trailing stretch (always the last layout item).
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def _add_thinking_bubble(self, text: str = "Thinking…") -> None:
        """Insert an animated 'working' bubble (spinner + label)."""

        bubble = QFrame()
        bubble.setObjectName("card")
        bubble.setProperty("role", "agent-bubble")
        inner = QHBoxLayout(bubble)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(10)
        spinner = Spinner(size=18, accent=self._theme().accent, parent=bubble)
        spinner.start()
        label = QLabel(text)
        label.setProperty("role", "empty-state-hint")
        inner.addWidget(spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        inner.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(bubble, 0)
        row.addStretch()
        bubble.setMaximumWidth(240)
        wrapper.setProperty("thinking", True)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, wrapper)
        self._scroll_to_bottom()

    def _remove_last_widget(self) -> None:
        """Remove the most recent thread widget (the trailing 'thinking' bubble).

        ``setParent(None)`` removes it from the display *synchronously* —
        ``deleteLater`` alone is not enough because the deferred-delete event
        is only processed when the event loop unwinds, so the bubble (and its
        spinner) would keep painting until then.
        """

        for i in range(self._chat_layout.count() - 1, -1, -1):
            item = self._chat_layout.itemAt(i)
            w = item.widget()
            if w is not None:
                self._chat_layout.removeItem(item)
                w.setParent(None)
                w.deleteLater()
                break

    def _scroll_to_bottom(self) -> None:
        bar = self._chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

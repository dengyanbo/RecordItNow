"""Search & RAG Q&A window — v0.4.1 polish pass.

Single column with a combined search bar (attached button), result
cards, and a chat thread below for the RAG agent. Both empty states use
tinted SVG icons; user bubbles use ``accent_subtle`` and right-align,
agent bubbles use the surface colour and left-align with a tail.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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

log = get_logger(__name__)


class _SearchEmptyState(QWidget):
    """Centered placeholder for the search-results / chat areas, with icon."""

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
        self.resize(960, 780)

        # --- top: search ------------------------------------------------------
        self._query = QLineEdit()
        self._query.setPlaceholderText("Search captures semantically…")
        self._query.setProperty("role", "search")
        self._query.returnPressed.connect(self._do_search)
        search_btn = QPushButton("Search")
        search_btn.setProperty("primary", True)
        search_btn.setProperty("role", "search-attached")
        search_btn.clicked.connect(self._do_search)
        top_row = QHBoxLayout()
        top_row.setSpacing(0)
        top_row.addWidget(self._query, 1)
        top_row.addWidget(search_btn, 0)

        self._results = QListWidget()
        self._results.setProperty("role", "cards")
        self._results.setSpacing(0)
        self._results.setFrameShape(QFrame.Shape.NoFrame)

        self._results_empty = _SearchEmptyState(
            "Search your captures",
            "Type a few words above to find captures by meaning, not just keyword.",
            icon_name="search",
        )
        self._results_stack = QStackedWidget()
        self._results_stack.addWidget(self._results_empty)
        self._results_stack.addWidget(self._results)

        # --- bottom: ask ------------------------------------------------------
        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(0, 0, 8, 0)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch()

        chat_scroll = QScrollArea()
        chat_scroll.setWidgetResizable(True)
        chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        chat_scroll.setWidget(self._chat_container)
        self._chat_scroll = chat_scroll

        self._chat_empty = _SearchEmptyState(
            "Ask anything about your captures",
            "Try: \"what was that error I saw on Tuesday?\" — answers come back "
            "with citations to specific captures.",
            icon_name="chat",
        )
        self._chat_stack = QStackedWidget()
        self._chat_stack.addWidget(self._chat_empty)
        self._chat_stack.addWidget(chat_scroll)

        self._question = QLineEdit()
        self._question.setPlaceholderText(
            "Ask anything (e.g. 'what was that error I saw on Tuesday?')"
        )
        self._question.setProperty("role", "search")
        self._question.returnPressed.connect(self._do_ask)
        ask_btn = QPushButton("Send")
        ask_btn.setProperty("primary", True)
        ask_btn.setProperty("role", "search-attached")
        ask_btn.clicked.connect(self._do_ask)
        ask_row = QHBoxLayout()
        ask_row.setSpacing(0)
        ask_row.addWidget(self._question, 1)
        ask_row.addWidget(ask_btn, 0)

        # --- assemble ---------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        heading = QLabel("Search & Ask")
        heading.setProperty("heading", "h1")
        layout.addWidget(heading)
        sub = QLabel(
            "Semantic search across your captures, plus a RAG agent that "
            "answers natural-language questions with citations."
        )
        sub.setProperty("role", "caption")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(16)

        search_heading = QLabel("Search captures")
        search_heading.setProperty("heading", "subtle")
        layout.addWidget(search_heading)
        layout.addLayout(top_row)
        layout.addSpacing(6)
        layout.addWidget(self._results_stack, 2)

        layout.addSpacing(16)
        ask_heading = QLabel("Ask")
        ask_heading.setProperty("heading", "subtle")
        layout.addWidget(ask_heading)
        layout.addWidget(self._chat_stack, 3)
        layout.addSpacing(6)
        layout.addLayout(ask_row)

        if self._agent is None:
            # Replace the chat empty state with a "no provider" warning.
            self._chat_empty.set_text(
                "Q&A is disabled",
                "No LLM provider is configured. Search still works. "
                "Open Settings → Analysis to pick a provider.",
            )

    # --- slots ----------------------------------------------------------------

    def _do_search(self) -> None:
        q = self._query.text().strip()
        if not q:
            return
        self._results.clear()
        placeholder = QListWidgetItem()
        placeholder.setText("Searching…")
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self._results.addItem(placeholder)
        self._results_stack.setCurrentWidget(self._results)
        self._pool.start(_SearchTask(q, self._signals))

    def _do_ask(self) -> None:
        if self._agent is None:
            return
        q = self._question.text().strip()
        if not q:
            return
        # Switch from empty state to chat scroller on first message.
        self._chat_stack.setCurrentIndex(1)
        self._add_chat_bubble(q, role="user")
        self._question.clear()
        self._add_chat_bubble("Thinking…", role="agent")
        self._pool.start(_AskTask(self._agent, q, self._signals))

    def _on_search_done(self, hits: list[SearchHit]) -> None:
        self._results.clear()
        self._results_stack.setCurrentWidget(self._results)
        if not hits:
            empty = QListWidgetItem("No matches — try different wording.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._results.addItem(empty)
            return
        for h in hits:
            card = _result_card(h)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, h.capture_id)
            self._results.addItem(item)
            self._results.setItemWidget(item, card)

    def _on_answer_done(self, answer: Answer) -> None:
        self._replace_last_agent_bubble(answer.text, citations=answer.hits)

    def _on_error(self, msg: str) -> None:
        log.error(f"Search window error: {msg}")
        self._replace_last_agent_bubble(f"Error: {msg}", citations=None)

    def _add_chat_bubble(self, text: str, *, role: str,
                         citations: list[SearchHit] | None = None) -> None:
        bubble = _chat_bubble(text, role, citations)
        # Insert before the trailing stretch (which is the last item).
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        # Auto-scroll to bottom.
        bar = self._chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _replace_last_agent_bubble(self, text: str, *,
                                   citations: list[SearchHit] | None) -> None:
        # Remove the last "Thinking…" placeholder.
        for i in range(self._chat_layout.count() - 1, -1, -1):
            item = self._chat_layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                self._chat_layout.removeItem(item)
                break
        self._add_chat_bubble(text, role="agent", citations=citations)

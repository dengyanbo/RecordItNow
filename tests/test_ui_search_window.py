"""UI tests for the unified Search & Ask window.

These exercise the mode toggle (persistence + placeholder/button sync) and
the submit routing for both modes, using a synchronous thread pool and
fake ``search`` / agent so no models or network are touched.
"""
from __future__ import annotations

from rin.config import RinConfig
from rin.rag.agent import Answer
from rin.rag.search import SearchHit
from rin.ui import search_window as sw


class _InlinePool:
    """QThreadPool stand-in that runs the runnable synchronously."""

    def start(self, task) -> None:
        task.run()


class _FakeAgent:
    def __init__(self, answer: Answer) -> None:
        self._answer = answer
        self.asked: list[str] = []

    def ask(self, question: str) -> Answer:
        self.asked.append(question)
        return self._answer


def _hit(cid: int = 1) -> SearchHit:
    return SearchHit(capture_id=cid, score=0.9, snippet="a snippet", metadata={})


def _labels(window: sw.SearchWindow) -> list[str]:
    """All QLabel texts currently in the conversation thread."""
    from PySide6.QtWidgets import QLabel

    return [lbl.text() for lbl in window._chat_container.findChildren(QLabel)]


def _thread_widgets(window: sw.SearchWindow) -> list:
    """Top-level widgets currently in the conversation thread (excludes the stretch)."""
    lay = window._chat_layout
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget()]


def test_no_provider_forces_search_mode(qapp, monkeypatch) -> None:
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: None)
    win = sw.SearchWindow(RinConfig())
    assert win._mode == "search"
    assert win._submit_btn.text() == "Search"
    assert not win._toggle._ask_btn.isEnabled()
    # Empty-state placeholder is shown before the first message.
    assert win._stack.currentIndex() == 0


def test_toggle_updates_ui_and_persists(qapp, monkeypatch) -> None:
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: _FakeAgent(Answer("x")))
    cfg = RinConfig()
    win = sw.SearchWindow(cfg)
    assert win._mode == "ask"  # default
    assert win._submit_btn.text() == "Send"

    win._on_mode_changed("search")
    assert win._mode == "search"
    assert win._submit_btn.text() == "Search"
    assert "Search captures" in win._input.placeholderText()
    # Persisted to config + on disk.
    assert cfg.search_mode == "search"
    assert RinConfig.load().search_mode == "search"


def test_search_mode_renders_results_message(qapp, monkeypatch) -> None:
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: None)
    monkeypatch.setattr(sw, "search", lambda query, k=8: [_hit(1), _hit(2)])
    win = sw.SearchWindow(RinConfig())
    win._pool = _InlinePool()

    win._input.setText("error dialog")
    win._submit()

    assert win._stack.currentIndex() == 1
    texts = _labels(win)
    assert "error dialog" in texts  # user bubble
    assert any(t.startswith("Found 2 capture") for t in texts)  # results header
    assert "cap-1" in texts and "cap-2" in texts


def test_search_mode_empty_results(qapp, monkeypatch) -> None:
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: None)
    monkeypatch.setattr(sw, "search", lambda query, k=8: [])
    win = sw.SearchWindow(RinConfig())
    win._pool = _InlinePool()

    win._input.setText("nothing matches")
    win._submit()

    assert any("No matches" in t for t in _labels(win))


def test_ask_mode_renders_answer_with_citations(qapp, monkeypatch) -> None:
    agent = _FakeAgent(Answer(text="Here is the answer.", hits=[_hit(7)]))
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: agent)
    win = sw.SearchWindow(RinConfig())
    win._pool = _InlinePool()
    assert win._mode == "ask"

    win._input.setText("what happened tuesday?")
    win._submit()

    texts = _labels(win)
    assert "what happened tuesday?" in texts  # user bubble
    assert "Here is the answer." in texts  # agent bubble
    assert "cap-7" in texts  # citation chip
    assert agent.asked == ["what happened tuesday?"]


def test_ask_mode_without_provider_shows_notice(qapp, monkeypatch) -> None:
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: None)
    win = sw.SearchWindow(RinConfig())
    # Force ask mode even though no agent (mirrors a provider removed mid-session).
    win._mode = "ask"
    win._input.setText("hello?")
    win._submit()

    assert any("Q&A is disabled" in t for t in _labels(win))


def test_blank_submit_is_noop(qapp, monkeypatch) -> None:
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: None)
    win = sw.SearchWindow(RinConfig())
    win._pool = _InlinePool()
    win._input.setText("   ")
    win._submit()
    # Still on the empty state, nothing added.
    assert win._stack.currentIndex() == 0


def test_thinking_bubble_fully_removed_after_result(qapp, monkeypatch) -> None:
    """Regression: the 'thinking' spinner bubble must be unparented when the

    result arrives — relying on deleteLater alone left it painting (a stray
    bubble) because DeferredDelete isn't processed by plain processEvents.
    """
    from rin.ui.progress import Spinner

    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: None)
    monkeypatch.setattr(sw, "search", lambda query, k=8: [_hit(1)])
    win = sw.SearchWindow(RinConfig())
    win._pool = _InlinePool()
    win._input.setText("checkout error")
    win._submit()

    # Exactly the user bubble + the results message remain (no thinking bubble),
    # and no Spinner is still parented under the thread.
    widgets = _thread_widgets(win)
    assert len(widgets) == 2
    assert all(not w.property("thinking") for w in widgets)
    assert not win._chat_container.findChildren(Spinner)


def test_thinking_bubble_fully_removed_after_answer(qapp, monkeypatch) -> None:
    from rin.ui.progress import Spinner

    agent = _FakeAgent(Answer(text="answer", hits=[_hit(3)]))
    monkeypatch.setattr(sw.RAGAgent, "from_config", lambda cfg: agent)
    win = sw.SearchWindow(RinConfig())
    win._pool = _InlinePool()
    win._input.setText("a question")
    win._submit()

    widgets = _thread_widgets(win)
    assert len(widgets) == 2  # user bubble + answer bubble
    assert all(not w.property("thinking") for w in widgets)
    assert not win._chat_container.findChildren(Spinner)

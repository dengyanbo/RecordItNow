"""Phase 2-C (v0.16.0): conversational LLM intake for new PoIs.

The intake is **deterministic in structure** but **LLM-synthesized in
the final step**. The dialog walks the user through 4 canned questions:

1. What do you want to track? (subject)
2. What words or phrases usually appear when it shows up? (keywords)
3. Any look-alike terms that should *not* count? (anti-keywords / aliases note)
4. How will RIN know it's wrapped up? (closed phrases)

After the user answers (or skips with "good enough"), one LLM call
synthesizes a :class:`TopicSpec`. If no provider is configured or the
LLM call fails, ``synth_topic_spec_from_chat`` builds a TopicSpec from
the answers using simple heuristics so the user still walks away with
something usable.

The deterministic-questions design keeps the UX testable and the LLM
cost bounded to one call per intake (vs. four).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from ..llm.base import LLMError, Provider
from ..skills.builtin.topic.skill import TopicSpec

QuestionId = Literal["subject", "keywords", "anti", "closed"]

QUESTIONS: tuple[tuple[QuestionId, str], ...] = (
    (
        "subject",
        "What do you want RIN to track? Describe it in one sentence "
        "(a project, customer, paper, person, ticket type, …).",
    ),
    (
        "keywords",
        "What words or phrases usually appear when this comes up on "
        "your screen? List a few, separated by commas.",
    ),
    (
        "anti",
        "Anything that looks related but should NOT count? "
        "(Leave blank if nothing comes to mind.)",
    ),
    (
        "closed",
        "How would you know it's wrapped up? "
        "(e.g. \"status: closed\", \"shipped\", \"archived\". Leave blank if there's no end state.)",
    ),
)


@dataclass(slots=True)
class ChatTurn:
    """One question/answer pair in the intake."""

    qid: QuestionId
    question: str
    answer: str = ""


@dataclass(slots=True)
class ChatState:
    """Mutable state for the conversational intake dialog."""

    turns: list[ChatTurn] = field(default_factory=list)
    finished: bool = False
    skipped: bool = False

    def __post_init__(self) -> None:
        if not self.turns:
            self.turns = [
                ChatTurn(qid=qid, question=q) for qid, q in QUESTIONS
            ]

    @property
    def current_index(self) -> int:
        for i, turn in enumerate(self.turns):
            if not turn.answer.strip() and not self.skipped:
                return i
        return len(self.turns)

    @property
    def is_done(self) -> bool:
        return self.skipped or self.current_index >= len(self.turns)

    def answer(self, text: str) -> None:
        if self.is_done:
            return
        idx = self.current_index
        if idx < len(self.turns):
            self.turns[idx].answer = text.strip()
        if self.current_index >= len(self.turns):
            self.finished = True

    def skip(self) -> None:
        """Mark the chat as voluntarily ended (early exit)."""

        self.skipped = True

    def get(self, qid: QuestionId) -> str:
        for turn in self.turns:
            if turn.qid == qid:
                return turn.answer
        return ""


_SYNTH_SYSTEM_PROMPT = (
    "You convert a user's brief description of a tracking topic into a "
    "JSON object suitable for a regex/keyword matcher. Be conservative: "
    "only include keywords the user actually mentioned or directly implied."
)


_SYNTH_USER_TEMPLATE = """A user just answered 4 questions to set up a Point-of-Interest tracker.

Q1 (subject): {subject}
Q2 (keywords seen on screen): {keywords}
Q3 (look-alikes that should not count): {anti}
Q4 (how they'd know it's wrapped up): {closed}

Return a single JSON object with this exact shape:
{{
  "name": str,            # short, capitalised; <= 30 chars
  "description": str,     # one sentence; <= 120 chars
  "keywords": [str, ...], # 1-6 items; words/phrases from Q1+Q2
  "closed_phrases": [str, ...] # 0-4 items; from Q4 only
}}
Output ONLY the JSON object, no preamble."""


def synth_topic_spec_from_chat(
    state: ChatState,
    *,
    provider: Provider | None = None,
) -> TopicSpec | None:
    """Turn a completed :class:`ChatState` into a :class:`TopicSpec`.

    Returns ``None`` if the user skipped before answering anything or
    the subject is blank. Otherwise builds a TopicSpec via the LLM (when
    a provider is given) or via simple heuristics (when not).
    """

    subject = state.get("subject")
    if not subject.strip():
        return None

    if provider is not None:
        try:
            spec = _synth_with_llm(state, provider)
            if spec is not None:
                return spec
        except LLMError:
            pass  # fall through to heuristic
        except (ValueError, json.JSONDecodeError, KeyError):
            pass

    return _synth_heuristic(state)


def _synth_with_llm(state: ChatState, provider: Provider) -> TopicSpec | None:
    prompt = _SYNTH_USER_TEMPLATE.format(
        subject=state.get("subject") or "(blank)",
        keywords=state.get("keywords") or "(none)",
        anti=state.get("anti") or "(none)",
        closed=state.get("closed") or "(none)",
    )
    reply = provider.analyze_text(prompt, system=_SYNTH_SYSTEM_PROMPT)
    payload = _extract_json(reply)
    if payload is None:
        return None
    name = str(payload.get("name", "")).strip()
    if not name:
        return None
    description = str(payload.get("description", "")).strip()
    keywords = _str_list(payload.get("keywords", []))
    closed = _str_list(payload.get("closed_phrases", []))
    return TopicSpec(
        name=name[:60],
        description=description[:200],
        keywords=keywords[:6] or [name],
        closed_phrases=closed[:4],
    )


def _synth_heuristic(state: ChatState) -> TopicSpec:
    subject = state.get("subject").strip()
    keywords_raw = state.get("keywords").strip()
    closed_raw = state.get("closed").strip()
    name = _first_phrase_or_words(subject) or subject[:30] or "New PoI"
    keywords = _split_csv(keywords_raw)
    if not keywords and subject:
        keywords = [name]
    closed = _split_csv(closed_raw)
    return TopicSpec(
        name=name[:60],
        description=subject[:200],
        keywords=keywords[:6] or [name],
        closed_phrases=closed[:4],
    )


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    # Strip common fences.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    # Heuristic: grab the first {...} block.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
    return out


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,;]+", value)
    return [p.strip() for p in parts if p.strip()]


_PHRASE_RE = re.compile(r"[A-Z][A-Za-z0-9]+(?:[ -][A-Z][A-Za-z0-9]+)+")


def _first_phrase_or_words(text: str) -> str:
    if not text:
        return ""
    match = _PHRASE_RE.search(text)
    if match is not None:
        return match.group(0).strip()
    words = text.strip().split()
    if not words:
        return ""
    capitalized = " ".join(w for w in words[:3] if w)
    return capitalized.strip(".,;:!?")


__all__ = [
    "QUESTIONS",
    "ChatState",
    "ChatTurn",
    "synth_topic_spec_from_chat",
]

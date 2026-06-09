"""Tests for Phase 2-C conversational intake."""
from __future__ import annotations

import json

from rin.llm.base import ImageAnalysis, LLMError, Provider, ProviderCapabilities
from rin.poi.conversational import (
    QUESTIONS,
    ChatState,
    synth_topic_spec_from_chat,
)
from rin.skills.builtin.topic.skill import TopicSpec


class _StubProvider(Provider):
    name = "stub"

    def __init__(self, response: str = "", *, raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[str] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="")

    def analyze_text(self, prompt, *, system=None):
        self.calls.append(prompt)
        if self.raise_exc:
            raise self.raise_exc
        return self.response

    def chat(self, messages):
        return ""


def test_initial_state_has_four_questions() -> None:
    state = ChatState()
    assert len(state.turns) == len(QUESTIONS) == 4
    assert state.current_index == 0
    assert not state.is_done


def test_state_advances_on_answer() -> None:
    state = ChatState()
    state.answer("Project Atlas")
    assert state.current_index == 1
    state.answer("atlas, migration")
    assert state.current_index == 2
    state.answer("")
    # Blank answers should leave the index where it was.
    assert state.current_index == 2
    state.answer("nothing")
    state.answer("status: done")
    assert state.is_done
    assert state.finished


def test_skip_marks_done() -> None:
    state = ChatState()
    state.answer("Project Atlas")
    state.skip()
    assert state.is_done


def test_synth_returns_none_when_no_subject() -> None:
    state = ChatState()
    state.skip()  # never answered anything
    assert synth_topic_spec_from_chat(state) is None


def test_synth_heuristic_without_provider() -> None:
    state = ChatState()
    state.answer("Project Atlas migration")
    state.answer("atlas, migration plan, lift-and-shift")
    state.answer("Atlanta office")  # anti
    state.answer("status: closed, archived")
    spec = synth_topic_spec_from_chat(state)
    assert isinstance(spec, TopicSpec)
    assert spec.name == "Project Atlas"
    assert "atlas" in spec.keywords or "Atlas" in spec.name
    assert "status: closed" in spec.closed_phrases
    assert "archived" in spec.closed_phrases


def test_synth_with_llm_parses_json_response() -> None:
    payload = {
        "name": "Atlas",
        "description": "Migration to Atlas platform",
        "keywords": ["atlas", "migration"],
        "closed_phrases": ["status: closed"],
    }
    provider = _StubProvider(response=json.dumps(payload))
    state = ChatState()
    state.answer("the Atlas migration project")
    state.answer("atlas, migration")
    state.answer("")
    state.answer("status: closed")
    spec = synth_topic_spec_from_chat(state, provider=provider)
    assert isinstance(spec, TopicSpec)
    assert spec.name == "Atlas"
    assert spec.keywords == ["atlas", "migration"]
    assert spec.closed_phrases == ["status: closed"]
    assert len(provider.calls) == 1


def test_synth_with_llm_handles_code_fence_wrapper() -> None:
    payload = '```json\n{"name": "Atlas", "keywords": ["atlas"]}\n```'
    provider = _StubProvider(response=payload)
    state = ChatState()
    state.answer("Atlas")
    state.answer("atlas")
    state.answer("")
    state.answer("")
    spec = synth_topic_spec_from_chat(state, provider=provider)
    assert spec is not None
    assert spec.name == "Atlas"


def test_synth_falls_back_when_llm_returns_garbage() -> None:
    provider = _StubProvider(response="I don't know")
    state = ChatState()
    state.answer("the Atlas project")
    state.answer("atlas")
    state.answer("")
    state.answer("")
    spec = synth_topic_spec_from_chat(state, provider=provider)
    assert spec is not None
    assert spec.name  # heuristic-built


def test_synth_falls_back_when_llm_raises() -> None:
    provider = _StubProvider(raise_exc=LLMError("boom"))
    state = ChatState()
    state.answer("Project Atlas")
    state.answer("atlas")
    state.answer("")
    state.answer("")
    spec = synth_topic_spec_from_chat(state, provider=provider)
    assert spec is not None
    assert spec.name == "Project Atlas"


def test_synth_heuristic_keywords_default_to_name() -> None:
    state = ChatState()
    state.answer("Quarterly board meeting prep")
    state.answer("")  # no keywords
    state.answer("")
    state.answer("")
    spec = synth_topic_spec_from_chat(state)
    assert spec is not None
    assert spec.keywords  # must always have at least one

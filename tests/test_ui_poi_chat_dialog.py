"""UI tests for the Phase 2-C conversational intake dialog."""
from __future__ import annotations

import json

import pytest

from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.ui.poi_chat_dialog import PoIChatDialog


class _StubProvider(Provider):
    name = "stub"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="")

    def analyze_text(self, prompt, *, system=None):
        self.calls.append(prompt)
        return self.response

    def chat(self, messages):
        return ""


def _drain(qapp, rounds: int = 3) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def test_chat_dialog_full_flow_returns_spec(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "name": "Atlas",
            "description": "Migration project",
            "keywords": ["atlas", "migration"],
            "closed_phrases": ["status: closed"],
        }
    )
    provider = _StubProvider(response=payload)
    dialog = PoIChatDialog(provider=provider)

    answers = ["Project Atlas migration", "atlas, migration", "Atalanta office", "status: closed"]
    for answer in answers:
        dialog._answer_edit.setPlainText(answer)
        dialog._on_next()
        _drain(qapp)

    # After 4 answers the dialog auto-finishes.
    assert dialog._result is not None
    assert dialog._result.name == "Atlas"
    assert dialog._result.keywords == ["atlas", "migration"]


def test_chat_dialog_skip_returns_none(qapp) -> None:
    dialog = PoIChatDialog(provider=None)
    dialog._answer_edit.setPlainText("Project Atlas")
    dialog._on_skip()
    assert dialog._result is None


def test_chat_dialog_finish_without_provider_uses_heuristic(qapp) -> None:
    dialog = PoIChatDialog(provider=None)
    dialog._answer_edit.setPlainText("Project Atlas")
    dialog._on_next()
    _drain(qapp)
    dialog._answer_edit.setPlainText("atlas, migration")
    dialog._on_finish()
    _drain(qapp)

    assert dialog._result is not None
    assert dialog._result.name == "Project Atlas"
    assert "atlas" in dialog._result.keywords or "Project Atlas" in dialog._result.keywords


def test_chat_dialog_finish_without_any_answer_acts_like_skip(qapp) -> None:
    dialog = PoIChatDialog(provider=None)
    dialog._on_finish()
    _drain(qapp)
    assert dialog._result is None

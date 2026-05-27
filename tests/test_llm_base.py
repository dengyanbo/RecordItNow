"""Provider ABC + dataclass sanity tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from rin.llm.base import (
    ImageAnalysis,
    LLMError,
    Message,
    Provider,
    ProviderCapabilities,
    ProviderUnavailable,
)


def test_image_analysis_defaults() -> None:
    ia = ImageAnalysis(summary="hi")
    assert ia.summary == "hi"
    assert ia.text == ""
    assert ia.entities == {}


def test_message_roles() -> None:
    Message(role="user", content="a")
    Message(role="system", content="b")
    Message(role="assistant", content="c")


def test_provider_unavailable_is_llmerror() -> None:
    assert issubclass(ProviderUnavailable, LLMError)


def test_provider_abc_requires_methods() -> None:
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


def test_health_check_returns_false_when_call_fails() -> None:
    class BoomProvider(Provider):
        name = "boom"

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(supports_vision=False, supports_chat=False)

        def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis:
            raise LLMError("nope")

        def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
            raise LLMError("nope")

        def chat(self, messages: list[Message]) -> str:
            raise LLMError("nope")

    assert BoomProvider().health_check() is False

"""OpenAI / Azure provider tests with an injected fake client.

Both providers accept a ``client_factory`` constructor argument that
returns whatever stand-in we want — this avoids hitting the real API
and works without any network or API key.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from rin.llm.azure_provider import AzureOpenAIProvider
from rin.llm.base import LLMError, Message, ProviderUnavailable
from rin.llm.openai_provider import OpenAIProvider


@dataclass
class _Choice:
    message: Any


@dataclass
class _Msg:
    content: str


@dataclass
class _Resp:
    choices: list[_Choice]


class _FakeChat:
    def __init__(self, response: str = "hello", capture: dict | None = None) -> None:
        self.response = response
        self.capture = capture if capture is not None else {}

    def create(self, **kwargs):
        self.capture["kwargs"] = kwargs
        return _Resp(choices=[_Choice(message=_Msg(content=self.response))])


class _FakeClient:
    def __init__(self, response: str = "hello", capture: dict | None = None) -> None:
        self.chat = _FakeNamespace(_FakeChat(response, capture))


class _FakeNamespace:
    def __init__(self, completions) -> None:
        self.completions = completions


def _factory(response: str, capture: dict):
    def _build(api_key: str, timeout: int) -> _FakeClient:
        capture["api_key"] = api_key
        capture["timeout"] = timeout
        return _FakeClient(response, capture)

    return _build


def test_openai_analyze_text_uses_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict = {}
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider = OpenAIProvider(client_factory=_factory("hi there", capture))
    assert provider.analyze_text("ping", system="be brief") == "hi there"
    assert capture["api_key"] == "test-key"
    messages = capture["kwargs"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == "ping"


def test_openai_missing_key_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("rin.llm.secrets._keyring", None)
    with pytest.raises(ProviderUnavailable):
        OpenAIProvider().analyze_text("hi")


def test_openai_analyze_image_encodes_data_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture: dict = {}
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    img = tmp_path / "s.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nabcd")
    provider = OpenAIProvider(client_factory=_factory("scene\nTEXT: hi", capture))
    result = provider.analyze_image(img)
    assert result.summary == "scene"
    assert result.text == "hi"
    user = capture["kwargs"]["messages"][0]
    types = [part["type"] for part in user["content"]]
    assert "image_url" in types
    url = next(p for p in user["content"] if p["type"] == "image_url")["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_openai_chat_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict = {}
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    provider = OpenAIProvider(client_factory=_factory("done", capture))
    out = provider.chat([Message(role="user", content="hi")])
    assert out == "done"
    assert capture["kwargs"]["messages"] == [{"role": "user", "content": "hi"}]


def test_openai_wraps_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    def broken_factory(api_key: str, timeout: int):
        class _C:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        raise RuntimeError("boom")

        return _C()

    provider = OpenAIProvider(client_factory=broken_factory)
    with pytest.raises(LLMError) as exc:
        provider.analyze_text("hi")
    assert "boom" in str(exc.value)


def test_azure_requires_endpoint_and_deployment() -> None:
    with pytest.raises(ProviderUnavailable):
        AzureOpenAIProvider(endpoint="", deployment="x")
    with pytest.raises(ProviderUnavailable):
        AzureOpenAIProvider(endpoint="https://x", deployment="")


def test_azure_uses_deployment_as_model(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict = {}
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-key")
    provider = AzureOpenAIProvider(
        endpoint="https://example.openai.azure.com",
        deployment="my-gpt4o",
        client_factory=_factory("ok", capture),
    )
    provider.analyze_text("x")
    assert capture["api_key"] == "az-key"
    assert capture["kwargs"]["model"] == "my-gpt4o"

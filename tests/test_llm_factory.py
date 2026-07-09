"""Factory routing tests."""
from __future__ import annotations

import pytest

from rin.config import LLMProviderConfig
from rin.llm import make_provider
from rin.llm.azure_provider import AzureOpenAIProvider
from rin.llm.base import ProviderUnavailable
from rin.llm.copilot_cli import CopilotCLIProvider
from rin.llm.openai_provider import OpenAIProvider


def test_factory_copilot_cli() -> None:
    p = make_provider(LLMProviderConfig(name="copilot_cli", model="gpt-5.2"))
    assert isinstance(p, CopilotCLIProvider)
    assert p.model == "gpt-5.2"


def test_factory_copilot_cli_auto() -> None:
    p = make_provider(LLMProviderConfig(name="copilot_cli", model="auto"))
    assert isinstance(p, CopilotCLIProvider)
    assert p.model == "auto"


def test_factory_openai() -> None:
    p = make_provider(LLMProviderConfig(name="openai", model="gpt-4o"))
    assert isinstance(p, OpenAIProvider)
    assert p.model == "gpt-4o"


def test_factory_azure_requires_endpoint_and_deployment() -> None:
    with pytest.raises(ProviderUnavailable):
        make_provider(LLMProviderConfig(name="azure"))


def test_factory_azure_ok() -> None:
    p = make_provider(
        LLMProviderConfig(
            name="azure",
            azure_endpoint="https://x.openai.azure.com",
            azure_deployment="dep",
        )
    )
    assert isinstance(p, AzureOpenAIProvider)
    assert p.model == "dep"


def test_factory_none_raises() -> None:
    with pytest.raises(ProviderUnavailable):
        make_provider(LLMProviderConfig(name="none"))

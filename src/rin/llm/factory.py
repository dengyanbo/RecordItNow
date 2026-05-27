"""Build a concrete :class:`Provider` from :class:`~rin.config.LLMProviderConfig`."""
from __future__ import annotations

from ..config import LLMProviderConfig
from .azure_provider import AzureOpenAIProvider
from .base import Provider, ProviderUnavailable
from .copilot_cli import CopilotCLIProvider
from .openai_provider import OpenAIProvider


def make_provider(cfg: LLMProviderConfig) -> Provider:
    """Return a provider matching ``cfg.name``. Raises ``ProviderUnavailable`` for ``"none"``."""

    name = cfg.name
    if name == "copilot_cli":
        return CopilotCLIProvider(
            model=cfg.model or None,
            reasoning_effort=cfg.reasoning_effort or None,
            timeout_seconds=cfg.timeout_seconds,
        )
    if name == "openai":
        return OpenAIProvider(
            model=cfg.model or "gpt-4o-mini",
            timeout_seconds=cfg.timeout_seconds,
        )
    if name == "azure":
        if not cfg.azure_endpoint or not cfg.azure_deployment:
            raise ProviderUnavailable(
                "Azure provider requires azure_endpoint and azure_deployment in config"
            )
        return AzureOpenAIProvider(
            endpoint=cfg.azure_endpoint,
            deployment=cfg.azure_deployment,
            timeout_seconds=cfg.timeout_seconds,
        )
    if name == "none":
        raise ProviderUnavailable("LLM provider disabled (name='none')")
    raise ProviderUnavailable(f"Unknown LLM provider name: {name!r}")

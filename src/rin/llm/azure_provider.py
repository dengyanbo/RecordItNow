"""Azure OpenAI provider.

Reuses :class:`OpenAIProvider`'s logic but constructs an
``AzureOpenAI`` client and uses the deployment name as the ``model``
parameter (per Azure conventions).

Resolution:
* API key — ``AZURE_OPENAI_API_KEY`` env var → keyring (``azure_openai_api_key``).
* Endpoint — from ``LLMProviderConfig.azure_endpoint``.
* Deployment — from ``LLMProviderConfig.azure_deployment``.
* API version — env var ``AZURE_OPENAI_API_VERSION`` (default
  ``2024-08-01-preview``).
"""
from __future__ import annotations

import os

from .base import ProviderCapabilities, ProviderUnavailable
from .openai_provider import OpenAIProvider
from .secrets import get_secret

DEFAULT_API_VERSION = "2024-08-01-preview"


class AzureOpenAIProvider(OpenAIProvider):
    name = "azure"

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str | None = None,
        timeout_seconds: int = 60,
        api_key: str | None = None,
        client_factory=None,
    ) -> None:
        if not endpoint:
            raise ProviderUnavailable("Azure endpoint is required")
        if not deployment:
            raise ProviderUnavailable("Azure deployment is required")
        super().__init__(
            model=deployment,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
            client_factory=client_factory,
        )
        self.endpoint = endpoint
        self.api_version = api_version or os.environ.get(
            "AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_vision=True,
            supports_chat=True,
            max_context_tokens=128_000,
        )

    def _resolve_key(self) -> str:
        if self._api_key:
            return self._api_key
        key = get_secret("azure_openai_api_key", env_var="AZURE_OPENAI_API_KEY")
        if not key:
            raise ProviderUnavailable(
                "Azure OpenAI API key not found. Set AZURE_OPENAI_API_KEY or store it in "
                "the keyring (rin/azure_openai_api_key)."
            )
        return key

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory(self._resolve_key(), self.timeout_seconds)
            return self._client
        try:
            from openai import AzureOpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("openai package not installed") from exc
        self._client = AzureOpenAI(
            api_key=self._resolve_key(),
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            timeout=self.timeout_seconds,
        )
        return self._client

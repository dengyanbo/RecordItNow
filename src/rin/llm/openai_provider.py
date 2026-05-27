"""OpenAI provider (chat completions + vision).

API key resolution order: ``OPENAI_API_KEY`` env var, then keyring entry
under service ``rin`` / username ``openai_api_key``. The client is
created lazily so the provider can be constructed even when the key is
missing — useful in the factory for capability inspection.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from .base import (
    ImageAnalysis,
    LLMError,
    Message,
    Provider,
    ProviderCapabilities,
    ProviderUnavailable,
)
from .secrets import get_secret

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        timeout_seconds: int = 60,
        api_key: str | None = None,
        client_factory=None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self._client_factory = client_factory
        self._client = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_vision=True,
            supports_chat=True,
            max_context_tokens=128_000,
        )

    # --- client -------------------------------------------------------------------

    def _resolve_key(self) -> str:
        if self._api_key:
            return self._api_key
        key = get_secret("openai_api_key", env_var="OPENAI_API_KEY")
        if not key:
            raise ProviderUnavailable(
                "OpenAI API key not found. Set OPENAI_API_KEY or store it in the keyring "
                "(rin/openai_api_key) via the settings dialog."
            )
        return key

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory(self._resolve_key(), self.timeout_seconds)
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("openai package not installed") from exc
        self._client = OpenAI(api_key=self._resolve_key(), timeout=self.timeout_seconds)
        return self._client

    # --- public API ---------------------------------------------------------------

    def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis:
        text_prompt = prompt or (
            "Analyze this desktop screenshot for an activity log. Reply with a 2-4 sentence "
            "summary, then a line starting with 'TEXT:' listing salient on-screen text."
        )
        data_url = _image_to_data_url(image_path)
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": text_prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            )
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise LLMError(f"OpenAI vision call failed: {exc}") from exc
        out = (resp.choices[0].message.content or "").strip()
        summary, text = _split_summary_and_text(out)
        return ImageAnalysis(summary=summary, text=text)

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            client = self._get_client()
            resp = client.chat.completions.create(model=self.model, messages=messages)
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise LLMError(f"OpenAI text call failed: {exc}") from exc
        return (resp.choices[0].message.content or "").strip()

    def chat(self, messages: list[Message]) -> str:
        wire = [{"role": m.role, "content": m.content} for m in messages]
        try:
            client = self._get_client()
            resp = client.chat.completions.create(model=self.model, messages=wire)
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise LLMError(f"OpenAI chat call failed: {exc}") from exc
        return (resp.choices[0].message.content or "").strip()


def _image_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _split_summary_and_text(out: str) -> tuple[str, str]:
    if "TEXT:" not in out:
        return out.strip(), ""
    head, _, tail = out.partition("TEXT:")
    return head.strip(), tail.strip()

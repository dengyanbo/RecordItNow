"""Abstract provider interface used by analysis, reports, and the RAG agent.

A concrete provider implements three operations:

* :meth:`Provider.analyze_image` — given a PNG path, return a short summary
  and any extracted text. Providers without vision capability must still
  implement this and may return an empty summary (the analysis pipeline
  will fall back to OCR-only text).
* :meth:`Provider.analyze_text` — single-prompt completion.
* :meth:`Provider.chat` — multi-turn conversation for the RAG agent.

All operations raise :class:`LLMError` on failure. :class:`ProviderUnavailable`
is raised when the underlying backend is not configured or not signed in.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class LLMError(RuntimeError):
    """Any LLM-call failure (timeout, HTTP error, malformed response, …)."""


class ProviderUnavailable(LLMError):
    """Backend is not configured or not signed in."""


@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ImageAnalysis:
    summary: str
    text: str = ""
    entities: dict = field(default_factory=dict)


@dataclass
class ProviderCapabilities:
    supports_vision: bool
    supports_chat: bool
    max_context_tokens: int = 8192


class Provider(ABC):
    """Abstract base class for LLM providers."""

    name: str = "provider"

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis: ...

    @abstractmethod
    def analyze_text(self, prompt: str, *, system: str | None = None) -> str: ...

    @abstractmethod
    def chat(self, messages: list[Message]) -> str: ...

    def health_check(self) -> bool:
        """Quick liveness probe. Default implementation tries a tiny ``analyze_text``."""

        try:
            self.analyze_text("ping", system="Reply with the word 'pong'.")
        except LLMError:
            return False
        return True

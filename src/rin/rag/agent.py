"""Retrieval-augmented Q&A loop.

1. Embed the user's question.
2. Pull the top-k matching captures from Chroma.
3. Build a prompt that injects those snippets.
4. Ask the active LLM provider for the answer + citations.

Returns an :class:`Answer` containing the prose response and the list of
hits that supplied the context.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import make_provider
from ..llm.base import LLMError, Message, Provider, ProviderUnavailable
from ..utils.logging import get_logger
from .embedder import Embedder, get_embedder
from .search import SearchHit, search

log = get_logger(__name__)

SYSTEM_PROMPT = (
    "You are RIN, the user's personal activity assistant. Answer the question "
    "using only the provided context excerpts. Cite each fact you use with "
    "the form (cap-{id}). If the context doesn't contain enough information, "
    "say so plainly."
)


@dataclass
class Answer:
    text: str
    hits: list[SearchHit] = field(default_factory=list)


class RAGAgent:
    def __init__(
        self,
        provider: Provider,
        *,
        embedder: Embedder | None = None,
        k: int = 5,
    ) -> None:
        self.provider = provider
        self.embedder = embedder or get_embedder()
        self.k = k

    @classmethod
    def from_config(cls, cfg) -> RAGAgent | None:
        try:
            provider = make_provider(cfg.llm)
        except ProviderUnavailable as exc:
            log.warning(f"RAGAgent unavailable: no LLM provider ({exc})")
            return None
        return cls(provider)

    def ask(self, question: str, *, kind: str | None = None) -> Answer:
        hits = search(question, k=self.k, kind=kind, embedder=self.embedder)
        if not hits:
            return Answer(text="I don't have any relevant captures indexed yet.", hits=[])
        context = "\n\n".join(
            f"[cap-{h.capture_id}] {h.snippet}" for h in hits
        )
        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(
                role="user",
                content=f"Question: {question}\n\nContext:\n{context}",
            ),
        ]
        try:
            answer_text = self.provider.chat(messages)
        except LLMError as exc:
            log.error(f"RAG agent LLM call failed: {exc}")
            answer_text = f"(LLM unavailable: {exc})"
        return Answer(text=answer_text, hits=hits)

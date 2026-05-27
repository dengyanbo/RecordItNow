"""RAG agent tests with mocked provider + embedder."""
from __future__ import annotations

import pytest

from rin.config import RinConfig
from rin.llm.base import Message, Provider, ProviderCapabilities
from rin.rag.agent import RAGAgent
from rin.rag.embedder import Embedder
from rin.storage import vector_store


class _StubEmbedder(Embedder):
    def __init__(self) -> None:
        super().__init__(model_name="stub")

    def embed(self, text: str) -> list[float]:
        return [0.5] * 8

    def embed_batch(self, texts):
        return [[0.5] * 8 for _ in texts]


class _StubProvider(Provider):
    name = "stub"
    model = "stub-1"

    def __init__(self) -> None:
        self.last_messages: list[Message] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        raise NotImplementedError

    def analyze_text(self, prompt, *, system=None):
        return "text"

    def chat(self, messages):
        self.last_messages = list(messages)
        return "Yes, the meeting (cap-1) discussed RecordItNow."


@pytest.fixture(autouse=True)
def fresh_chroma():
    vector_store.reset()
    yield
    vector_store.reset()


def _seed_chroma(embedder):
    docs = ["Meeting with Alice about RecordItNow", "Other capture"]
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=["cap-1", "cap-2"],
        documents=docs,
        embeddings=embedder.embed_batch(docs),
        metadatas=[
            {"capture_id": 1, "kind": "screenshot", "started_at": "2026-05-21T10:00:00"},
            {"capture_id": 2, "kind": "screenshot", "started_at": "2026-05-21T11:00:00"},
        ],
    )


def test_agent_returns_answer_with_hits() -> None:
    embedder = _StubEmbedder()
    _seed_chroma(embedder)
    provider = _StubProvider()
    agent = RAGAgent(provider, embedder=embedder, k=2)
    answer = agent.ask("Tell me about the meeting")
    assert "RecordItNow" in answer.text
    assert len(answer.hits) == 2
    # Provider received system+user messages with context block.
    assert any("Context:" in m.content for m in provider.last_messages)


def test_agent_handles_empty_index() -> None:
    embedder = _StubEmbedder()
    provider = _StubProvider()
    agent = RAGAgent(provider, embedder=embedder)
    answer = agent.ask("anything")
    assert "relevant captures" in answer.text.lower()
    assert answer.hits == []


def test_agent_from_config_returns_none_when_provider_unavailable() -> None:
    cfg = RinConfig()
    cfg.llm.name = "none"
    assert RAGAgent.from_config(cfg) is None

"""Search round-trip tests with a fake embedder + real Chroma."""
from __future__ import annotations

import pytest

from rin.rag.embedder import Embedder
from rin.rag.search import search
from rin.storage import vector_store


class _StaticEmbedder(Embedder):
    """Tiny embedder that returns one-hot vectors based on the query text."""

    def __init__(self) -> None:
        super().__init__(model_name="static")
        self.dim_value = 8

    @property
    def dim(self) -> int:
        return self.dim_value

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts):
        result = []
        for t in texts:
            vec = [0.0] * self.dim_value
            for i, ch in enumerate(t[: self.dim_value]):
                vec[i] = (ord(ch) % 17) / 17.0
            result.append(vec)
        return result


@pytest.fixture(autouse=True)
def fresh_chroma():
    vector_store.reset()
    yield
    vector_store.reset()


def _seed():
    embedder = _StaticEmbedder()
    ids = ["cap-1", "cap-2", "cap-3"]
    docs = [
        "Meeting with Alice about RecordItNow",
        "Debugging Python ImportError in main.py",
        "Writing markdown report",
    ]
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=ids,
        documents=docs,
        embeddings=embedder.embed_batch(docs),
        metadatas=[
            {"capture_id": 1, "kind": "screenshot", "started_at": "2026-05-21T10:00:00"},
            {"capture_id": 2, "kind": "screenshot", "started_at": "2026-05-21T11:00:00"},
            {"capture_id": 3, "kind": "video", "started_at": "2026-05-21T12:00:00"},
        ],
    )
    return embedder


def test_search_returns_hits() -> None:
    embedder = _seed()
    hits = search("Meeting with Alice about RecordItNow", k=2, embedder=embedder)
    assert len(hits) >= 1
    # Same text used to seed → top hit should be cap-1.
    assert hits[0].capture_id == 1
    assert hits[0].started_at is not None


def test_search_filter_by_kind() -> None:
    embedder = _seed()
    hits = search("anything", k=10, kind="video", embedder=embedder)
    assert all(h.metadata.get("kind") == "video" for h in hits)
    assert {h.capture_id for h in hits} == {3}


def test_search_empty_collection_returns_empty() -> None:
    embedder = _StaticEmbedder()
    hits = search("anything", k=5, embedder=embedder)
    assert hits == []

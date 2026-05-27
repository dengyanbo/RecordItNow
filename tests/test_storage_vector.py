"""ChromaDB vector-store smoke tests using random embeddings."""
from __future__ import annotations

import random

import pytest

from rin.storage import vector_store as vs


@pytest.fixture(autouse=True)
def fresh_client():
    vs.reset()
    yield
    vs.reset()


def _vec(seed: int, dim: int = 64) -> list[float]:
    rng = random.Random(seed)
    return [rng.random() for _ in range(dim)]


def test_upsert_and_query_round_trip() -> None:
    ids = [f"cap-{i}" for i in range(3)]
    docs = [
        "a meeting transcript",
        "code review notes",
        "vs code screenshot",
    ]
    embs = [_vec(i) for i in range(3)]
    metas = [{"capture_id": i, "kind": "screenshot"} for i in range(3)]

    vs.upsert(
        collection=vs.CAPTURES_COLLECTION,
        ids=ids,
        documents=docs,
        embeddings=embs,
        metadatas=metas,
    )
    assert vs.count(collection=vs.CAPTURES_COLLECTION) == 3

    results = vs.query(
        collection=vs.CAPTURES_COLLECTION,
        query_embeddings=[_vec(0)],
        n_results=2,
    )
    assert len(results) == 1
    # Querying with the exact same embedding as cap-0 should return cap-0 first.
    assert results[0][0].id == "cap-0"
    assert results[0][0].score > 0.9


def test_delete_removes_entries() -> None:
    vs.upsert(
        collection=vs.CAPTURES_COLLECTION,
        ids=["a", "b"],
        documents=["x", "y"],
        embeddings=[_vec(1), _vec(2)],
        metadatas=[{"k": 1}, {"k": 2}],
    )
    vs.delete(collection=vs.CAPTURES_COLLECTION, ids=["a"])

    results = vs.query(
        collection=vs.CAPTURES_COLLECTION,
        query_embeddings=[_vec(1)],
        n_results=10,
    )
    ids = [hit.id for hits in results for hit in hits]
    assert "a" not in ids
    assert "b" in ids

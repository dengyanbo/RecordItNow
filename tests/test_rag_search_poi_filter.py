"""Phase 1-C (v0.12.0): rin.rag.search filters by tracked POI.

When ``pois=["Atlas"]`` is passed, search inflates the candidate set
from Chroma and then Python-filters by the indexed ``bucket_keys``
metadata so only captures linked to the topic come back. Bare names
are treated as topic POIs; ``skill:key`` strings (e.g.
``support_ticket:T-1``) target other skills.
"""
from __future__ import annotations

import pytest

from rin.rag.embedder import Embedder
from rin.rag.search import _matches_any_poi, _normalize_poi_needles, search
from rin.storage import vector_store


class _StaticEmbedder(Embedder):
    def __init__(self) -> None:
        super().__init__(model_name="static")

    @property
    def dim(self) -> int:
        return 4

    def embed(self, text: str) -> list[float]:
        return [float(len(text) % 7), 0.1, 0.2, 0.3]

    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


@pytest.fixture(autouse=True)
def fresh_chroma():
    vector_store.reset()
    yield
    vector_store.reset()


def _seed_indexed_captures() -> _StaticEmbedder:
    embedder = _StaticEmbedder()
    ids = [f"cap-{i}" for i in (1, 2, 3, 4)]
    docs = [
        "Atlas design review",
        "Beacon implementation work",
        "Atlas debugging session",
        "Unrelated capture",
    ]
    metas = [
        {"capture_id": 1, "kind": "screenshot", "bucket_keys": "|topic:Atlas|"},
        {"capture_id": 2, "kind": "screenshot", "bucket_keys": "|topic:Beacon|"},
        {
            "capture_id": 3,
            "kind": "screenshot",
            "bucket_keys": "|topic:Atlas|support_ticket:T-1|",
        },
        {"capture_id": 4, "kind": "screenshot"},
    ]
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=ids,
        documents=docs,
        embeddings=embedder.embed_batch(docs),
        metadatas=metas,
    )
    return embedder


def test_normalize_poi_needles_bare_names_become_topic_prefixed() -> None:
    assert _normalize_poi_needles(["Atlas"]) == ["|topic:Atlas|"]
    assert _normalize_poi_needles(["Atlas", "support_ticket:T-1"]) == [
        "|topic:Atlas|",
        "|support_ticket:T-1|",
    ]


def test_normalize_poi_needles_empty_handling() -> None:
    assert _normalize_poi_needles(None) == []
    assert _normalize_poi_needles([]) == []
    assert _normalize_poi_needles(["", "   "]) == []


def test_matches_any_poi_substring_lookup() -> None:
    meta = {"bucket_keys": "|topic:Atlas|topic:Beacon|"}
    assert _matches_any_poi(meta, ["|topic:Atlas|"]) is True
    assert _matches_any_poi(meta, ["|topic:Cinder|"]) is False
    assert _matches_any_poi({}, ["|topic:Atlas|"]) is False
    assert _matches_any_poi({"bucket_keys": ""}, ["|topic:Atlas|"]) is False


def test_matches_any_poi_distinguishes_partial_names() -> None:
    """|topic:Atlas| must not match the longer |topic:AtlasFrontend|."""

    meta = {"bucket_keys": "|topic:AtlasFrontend|"}
    assert _matches_any_poi(meta, ["|topic:Atlas|"]) is False
    assert _matches_any_poi(meta, ["|topic:AtlasFrontend|"]) is True


def test_search_filters_to_only_atlas_captures() -> None:
    embedder = _seed_indexed_captures()
    hits = search("Atlas", k=10, pois=["Atlas"], embedder=embedder)
    cap_ids = {h.capture_id for h in hits}
    # cap-1 and cap-3 both touch Atlas; cap-2/cap-4 don't.
    assert cap_ids == {1, 3}


def test_search_with_no_pois_returns_everything() -> None:
    embedder = _seed_indexed_captures()
    hits = search("Atlas", k=10, embedder=embedder)
    assert {h.capture_id for h in hits} == {1, 2, 3, 4}


def test_search_pois_supports_skill_qualified_keys() -> None:
    embedder = _seed_indexed_captures()
    hits = search(
        "anything", k=10, pois=["support_ticket:T-1"], embedder=embedder
    )
    assert {h.capture_id for h in hits} == {3}


def test_search_with_unknown_poi_returns_empty() -> None:
    embedder = _seed_indexed_captures()
    hits = search("anything", k=10, pois=["NoSuchTopic"], embedder=embedder)
    assert hits == []


def test_search_pois_respects_k_cap() -> None:
    """Even when many captures match the POI, only k results come back."""

    embedder = _StaticEmbedder()
    ids = [f"cap-{i}" for i in range(20)]
    docs = [f"Atlas capture {i}" for i in range(20)]
    metas = [
        {"capture_id": i, "kind": "screenshot", "bucket_keys": "|topic:Atlas|"}
        for i in range(20)
    ]
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=ids,
        documents=docs,
        embeddings=embedder.embed_batch(docs),
        metadatas=metas,
    )

    hits = search("Atlas", k=3, pois=["Atlas"], embedder=embedder)
    assert len(hits) == 3


def test_search_pois_inflates_candidate_set() -> None:
    """Filter post-processing must not silently return fewer than k.

    Mix non-matching captures into the result so naive ``n_results=k`` would
    starve. With the 4x inflation we still return ``k`` hits.
    """

    embedder = _StaticEmbedder()
    ids = []
    docs = []
    metas = []
    # 10 non-matching captures first, then 5 matching.
    for i in range(10):
        ids.append(f"cap-noise-{i}")
        docs.append(f"noise {i}")
        metas.append({"capture_id": 1000 + i, "kind": "screenshot"})
    for i in range(5):
        ids.append(f"cap-match-{i}")
        docs.append(f"atlas match {i}")
        metas.append(
            {
                "capture_id": 2000 + i,
                "kind": "screenshot",
                "bucket_keys": "|topic:Atlas|",
            }
        )
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=ids,
        documents=docs,
        embeddings=embedder.embed_batch(docs),
        metadatas=metas,
    )

    hits = search("atlas", k=3, pois=["Atlas"], embedder=embedder)
    assert len(hits) == 3
    assert all("bucket_keys" in h.metadata for h in hits)

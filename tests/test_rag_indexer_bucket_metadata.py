"""Phase 1-C (v0.12.0): indexer attaches bucket metadata to captures.

The new ``bucket_keys`` field is a pipe-padded string like
``"|topic:Atlas|topic:Beacon|"``. The padding lets a Python post-filter
match ``|topic:Atlas|`` cleanly without false hits from substring
collisions (e.g. ``Atlas`` would match ``AtlasFrontend`` without the
``|`` boundary).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.rag.embedder import Embedder
from rin.rag.indexer import (
    bucket_keys_for_capture,
    encode_bucket_keys,
    index_capture,
)
from rin.storage import db, init_db, session, vector_store
from rin.storage.models import Analysis, Bucket, Capture, CaptureBucket


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    vector_store.reset()
    yield tmp_path
    vector_store.reset()
    db.reset()
    paths_mod.reset_cache()


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


def _insert_capture(when: datetime, text: str) -> int:
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", started_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=text, ocr_text="ocr"))
        s.flush()
        return cap.id


def _link_buckets(cap_id: int, buckets: list[tuple[str, str]]) -> list[int]:
    """Create (skill, key) buckets and link them to cap_id."""

    ids: list[int] = []
    with session() as s:
        for skill, key in buckets:
            b = Bucket(skill_name=skill, key=key, title=key)
            s.add(b)
            s.flush()
            ids.append(b.id)
            s.add(CaptureBucket(capture_id=cap_id, bucket_id=b.id))
        s.flush()
    return ids


def test_encode_bucket_keys_pads_with_pipes() -> None:
    out = encode_bucket_keys(["topic:Atlas", "topic:Beacon"])
    assert out == "|topic:Atlas|topic:Beacon|"
    assert out.startswith("|") and out.endswith("|")


def test_encode_bucket_keys_empty_returns_empty() -> None:
    assert encode_bucket_keys([]) == ""
    assert encode_bucket_keys(["", "  "]) == ""


def test_bucket_keys_for_capture_returns_skill_qualified_keys(rin_db: Path) -> None:
    cap_id = _insert_capture(datetime(2026, 6, 1, 10, 0), "summary")
    _link_buckets(cap_id, [("topic", "Atlas"), ("support_ticket", "T-1")])
    ids, keys = bucket_keys_for_capture(cap_id)
    assert len(ids) == 2
    assert sorted(keys) == ["support_ticket:T-1", "topic:Atlas"]


def test_bucket_keys_for_capture_empty_when_no_buckets(rin_db: Path) -> None:
    cap_id = _insert_capture(datetime(2026, 6, 1, 10, 0), "summary")
    ids, keys = bucket_keys_for_capture(cap_id)
    assert ids == []
    assert keys == []


def test_index_capture_writes_bucket_keys_metadata(rin_db: Path) -> None:
    cap_id = _insert_capture(
        datetime(2026, 6, 1, 10, 0), "Worked on Project Atlas today"
    )
    _link_buckets(cap_id, [("topic", "Atlas"), ("topic", "Beacon")])
    embedder = _StaticEmbedder()
    assert index_capture(cap_id, embedder=embedder) is True

    results = vector_store.query(
        collection=vector_store.CAPTURES_COLLECTION,
        query_embeddings=[embedder.embed("query")],
        n_results=10,
    )
    assert results and results[0], "capture should be indexed"
    meta = next(h.metadata for h in results[0] if h.id == f"cap-{cap_id}")
    assert meta["capture_id"] == cap_id
    assert meta["kind"] == "screenshot"
    # Pipe-padded string with both topic keys.
    assert "|topic:Atlas|" in meta["bucket_keys"]
    assert "|topic:Beacon|" in meta["bucket_keys"]
    assert meta["bucket_keys"].startswith("|")
    assert meta["bucket_keys"].endswith("|")
    # CSV of bucket ids present (one or more numeric ids).
    assert all(part.isdigit() for part in meta["bucket_ids_csv"].split(","))


def test_index_capture_without_buckets_omits_metadata(rin_db: Path) -> None:
    cap_id = _insert_capture(datetime(2026, 6, 1, 10, 0), "Random text")
    embedder = _StaticEmbedder()
    assert index_capture(cap_id, embedder=embedder) is True

    results = vector_store.query(
        collection=vector_store.CAPTURES_COLLECTION,
        query_embeddings=[embedder.embed("query")],
        n_results=10,
    )
    meta = next(h.metadata for h in results[0] if h.id == f"cap-{cap_id}")
    # No bucket fields when capture has no buckets.
    assert "bucket_keys" not in meta
    assert "bucket_ids_csv" not in meta


def test_summarizer_push_to_index_uses_bucket_keys(rin_db: Path) -> None:
    """`_push_to_index` in summarizer.py uses the same enrichment."""

    from rin.analysis.summarizer import _push_to_index

    cap_id = _insert_capture(datetime(2026, 6, 1, 10, 0), "txt")
    _link_buckets(cap_id, [("topic", "Atlas")])
    emb = _StaticEmbedder()
    _push_to_index(cap_id, "joined text", lambda t: emb.embed(t))

    results = vector_store.query(
        collection=vector_store.CAPTURES_COLLECTION,
        query_embeddings=[emb.embed("query")],
        n_results=10,
    )
    meta = next(h.metadata for h in results[0] if h.id == f"cap-{cap_id}")
    assert meta["bucket_keys"] == "|topic:Atlas|"

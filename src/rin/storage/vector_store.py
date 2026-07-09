"""ChromaDB persistent client used by the Phase 8 RAG layer.

Two collections live in the same persist directory:

* ``captures`` — embeddings of (summary + OCR + transcript) per capture.
* ``reports``  — chunked report sections.

Both use cosine distance.

``chromadb`` is imported **lazily** inside :func:`get_client` rather than at
module top level. It is a heavy native import (~2-3 s, pulls numpy + its own
deps) and ``rin.storage`` is imported on the startup critical path, so an
eager import here froze the tray for seconds on first launch. We only pay
the cost on the first actual vector operation (first analysis or search),
which already runs off the main thread.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import paths

CAPTURES_COLLECTION = "captures"
REPORTS_COLLECTION = "reports"

_client: Any | None = None


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    document: str
    metadata: dict[str, Any]


def get_client() -> Any:
    """Return (and cache) a Chroma ``PersistentClient`` rooted at the RIN chroma dir."""

    global _client
    if _client is None:
        import chromadb  # lazy: keep this heavy import off the startup path

        _client = chromadb.PersistentClient(path=str(paths.chroma_dir()))
    return _client


def reset() -> None:
    """Drop the cached client. Used by tests after switching ``RIN_DATA_DIR``."""

    global _client
    _client = None


def _collection(name: str) -> Any:
    return get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert(
    *,
    collection: str,
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]] | None = None,
) -> None:
    if not ids:
        return
    _collection(collection).upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def query(
    *,
    collection: str,
    query_embeddings: list[list[float]],
    n_results: int = 10,
    where: dict | None = None,
) -> list[list[SearchHit]]:
    coll = _collection(collection)
    res = coll.query(
        query_embeddings=query_embeddings,
        n_results=n_results,
        where=where,
    )
    out: list[list[SearchHit]] = []
    ids_batches = res.get("ids") or []
    docs_batches = res.get("documents") or [[None] * len(b) for b in ids_batches]
    metas_batches = res.get("metadatas") or [[None] * len(b) for b in ids_batches]
    dists_batches = res.get("distances") or [[0.0] * len(b) for b in ids_batches]
    for q_ids, q_docs, q_meta, q_dist in zip(
        ids_batches, docs_batches, metas_batches, dists_batches, strict=False
    ):
        out.append(
            [
                SearchHit(
                    id=i,
                    score=float(1.0 - d) if d is not None else 0.0,
                    document=doc or "",
                    metadata=m or {},
                )
                for i, doc, m, d in zip(q_ids, q_docs, q_meta, q_dist, strict=False)
            ]
        )
    return out


def delete(*, collection: str, ids: list[str]) -> None:
    if not ids:
        return
    _collection(collection).delete(ids=ids)


def count(*, collection: str) -> int:
    return _collection(collection).count()

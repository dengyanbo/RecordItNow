"""Vector search over the ``captures`` collection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..storage import vector_store
from ..utils.logging import get_logger
from .embedder import Embedder, get_embedder

log = get_logger(__name__)


@dataclass
class SearchHit:
    capture_id: int
    score: float
    snippet: str
    metadata: dict
    started_at: datetime | None = None


def search(
    query: str,
    *,
    k: int = 5,
    kind: str | None = None,
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    """Return top-``k`` matching captures for ``query``."""

    embedder = embedder or get_embedder()
    vec = embedder.embed(query)
    where = {"kind": kind} if kind else None
    results = vector_store.query(
        collection=vector_store.CAPTURES_COLLECTION,
        query_embeddings=[vec],
        n_results=k,
        where=where,
    )
    hits: list[SearchHit] = []
    if not results:
        return hits
    for raw in results[0]:
        meta = raw.metadata or {}
        cap_id = int(meta.get("capture_id", 0)) or _id_to_int(raw.id)
        started_at = _parse_dt(meta.get("started_at"))
        hits.append(
            SearchHit(
                capture_id=cap_id,
                score=raw.score,
                snippet=raw.document[:400],
                metadata=meta,
                started_at=started_at,
            )
        )
    return hits


def _id_to_int(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else 0


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None

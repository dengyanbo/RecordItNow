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
    pois: list[str] | None = None,
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    """Return top-``k`` matching captures for ``query``.

    ``pois`` (Phase 1-C, v0.12.0): when non-empty, restrict results to
    captures linked to at least one of these tracked POIs. Each entry
    is matched against the indexed ``bucket_keys`` field as ``topic:<name>``;
    pass raw ``skill_name:key`` strings (e.g. ``support_ticket:T-1``) to
    filter on a different skill.

    Because Chroma metadata is scalar-only, the POI filter is applied
    in Python over a wider hit set. We multiply ``k`` by 4 (capped at
    50) before querying to keep the final top-``k`` populated.
    """

    embedder = embedder or get_embedder()
    vec = embedder.embed(query)
    where = {"kind": kind} if kind else None

    # Inflate the candidate set when POI filtering is active so the
    # post-filter doesn't starve the caller's k.
    needles = _normalize_poi_needles(pois)
    fetch_n = k
    if needles:
        fetch_n = min(50, max(k * 4, k))

    results = vector_store.query(
        collection=vector_store.CAPTURES_COLLECTION,
        query_embeddings=[vec],
        n_results=fetch_n,
        where=where,
    )
    hits: list[SearchHit] = []
    if not results:
        return hits
    for raw in results[0]:
        meta = raw.metadata or {}
        if needles and not _matches_any_poi(meta, needles):
            continue
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
        if len(hits) >= k:
            break
    return hits


def _normalize_poi_needles(pois: list[str] | None) -> list[str]:
    """Build the pipe-padded substrings used to match Chroma metadata.

    ``["Atlas", "topic:Beacon", "support_ticket:T-1"]``
        →
    ``["|topic:Atlas|", "|topic:Beacon|", "|support_ticket:T-1|"]``

    Bare names are assumed to be topic POIs (the common case).
    """

    if not pois:
        return []
    out: list[str] = []
    for raw in pois:
        if not raw or not raw.strip():
            continue
        cleaned = raw.strip()
        if ":" not in cleaned:
            cleaned = f"topic:{cleaned}"
        out.append(f"|{cleaned}|")
    return out


def _matches_any_poi(meta: dict, needles: list[str]) -> bool:
    keys = str(meta.get("bucket_keys") or "")
    if not keys:
        return False
    return any(needle in keys for needle in needles)


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

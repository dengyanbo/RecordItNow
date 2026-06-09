"""Upsert analyzed captures into the ChromaDB ``captures`` collection.

Phase 6's summarizer already accepts an ``embedder`` callable — we
provide one. :func:`index_capture` and :func:`index_pending` are also
exposed so an operator can re-index after a model change.

Phase 1-C (v0.12.0) enriches metadata with ``bucket_keys`` so search
can post-filter by tracked POIs. ``bucket_keys`` is stored as a
pipe-padded string (e.g. ``"|topic:Atlas|topic:Beacon|"``) because
Chroma metadata only supports scalar values; the leading/trailing
pipes guarantee unambiguous substring matches at query time.
"""
from __future__ import annotations

from sqlalchemy import select

from ..storage import session, vector_store
from ..storage.models import Analysis, Bucket, Capture, CaptureBucket
from ..utils.logging import get_logger
from .embedder import Embedder, get_embedder

log = get_logger(__name__)


def _gather_text(cap: Capture) -> str:
    parts: list[str] = []
    for a in cap.analyses:
        if a.summary:
            parts.append(a.summary)
        if a.ocr_text:
            parts.append(a.ocr_text)
    for t in cap.transcripts:
        if t.text:
            parts.append(t.text)
    return "\n\n".join(parts).strip()


def bucket_keys_for_capture(capture_id: int) -> tuple[list[int], list[str]]:
    """Return ``(ids, keys)`` for every bucket linked to ``capture_id``.

    ``keys`` are formatted as ``"{skill_name}:{key}"`` so a single string
    can disambiguate same-key buckets across skills.
    """

    with session() as s:
        rows = s.execute(
            select(Bucket.id, Bucket.skill_name, Bucket.key)
            .join(CaptureBucket, CaptureBucket.bucket_id == Bucket.id)
            .where(CaptureBucket.capture_id == capture_id)
            .order_by(Bucket.skill_name.asc(), Bucket.key.asc())
        ).all()
    ids: list[int] = []
    keys: list[str] = []
    for bid, skill_name, key in rows:
        ids.append(bid)
        keys.append(f"{skill_name}:{key}")
    return ids, keys


def encode_bucket_keys(keys: list[str]) -> str:
    """Pipe-pad a key list for substring search in Chroma metadata.

    ``[]`` → ``""`` so the absence of buckets is distinguishable from a
    single empty bucket.
    """

    if not keys:
        return ""
    cleaned = [k.strip() for k in keys if k and k.strip()]
    if not cleaned:
        return ""
    return "|" + "|".join(cleaned) + "|"


def index_capture(capture_id: int, *, embedder: Embedder | None = None) -> bool:
    embedder = embedder or get_embedder()
    with session() as s:
        cap = s.get(Capture, capture_id)
        if cap is None:
            return False
        text = _gather_text(cap)
        if not text:
            log.debug(f"index_capture({capture_id}): no text to index")
            return False
        meta = {
            "capture_id": cap.id,
            "kind": cap.kind,
            "started_at": cap.started_at.isoformat() if cap.started_at else "",
        }
    bucket_ids, bucket_keys = bucket_keys_for_capture(capture_id)
    if bucket_ids:
        meta["bucket_ids_csv"] = ",".join(str(i) for i in bucket_ids)
        meta["bucket_keys"] = encode_bucket_keys(bucket_keys)
    vec = embedder.embed(text)
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=[f"cap-{capture_id}"],
        documents=[text[:4000]],
        embeddings=[vec],
        metadatas=[meta],
    )
    log.info(
        f"Indexed capture {capture_id} ({len(text)} chars; "
        f"{len(bucket_ids)} bucket(s))"
    )
    return True


def index_pending(*, embedder: Embedder | None = None, limit: int = 100) -> list[int]:
    """Re-index every analyzed capture currently missing from the vector store.

    Cheap heuristic: we don't track per-capture indexed state in SQL; instead
    we ask Chroma whether the id exists and skip if so. For the bulk
    re-index command, the operator can clear the collection first.
    """

    embedder = embedder or get_embedder()
    with session() as s:
        rows = s.scalars(
            select(Capture)
            .join(Analysis)
            .where(Capture.status == "analyzed")
            .limit(limit)
        ).unique().all()
        ids = [c.id for c in rows]
    indexed: list[int] = []
    for cap_id in ids:
        try:
            if index_capture(cap_id, embedder=embedder):
                indexed.append(cap_id)
        except Exception as exc:
            log.error(f"index_capture({cap_id}) failed: {exc}")
    return indexed

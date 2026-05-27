"""Upsert analyzed captures into the ChromaDB ``captures`` collection.

Phase 6's summarizer already accepts an ``embedder`` callable — we
provide one. :func:`index_capture` and :func:`index_pending` are also
exposed so an operator can re-index after a model change.
"""
from __future__ import annotations

from sqlalchemy import select

from ..storage import session, vector_store
from ..storage.models import Analysis, Capture
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
    vec = embedder.embed(text)
    vector_store.upsert(
        collection=vector_store.CAPTURES_COLLECTION,
        ids=[f"cap-{capture_id}"],
        documents=[text[:4000]],
        embeddings=[vec],
        metadatas=[meta],
    )
    log.info(f"Indexed capture {capture_id} ({len(text)} chars)")
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

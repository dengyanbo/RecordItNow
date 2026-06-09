"""Summarizer: per-capture roll-up + DB write + vector index push.

The summarizer is the analysis pipeline's entry point. It:

1. Loads the capture from the DB.
2. For screenshots, calls :func:`analyze_image` per monitor file.
3. For videos, calls :func:`analyze_video` per file.
4. **Pre-classifies** the capture (skills detect POIs from raw OCR + transcript).
5. Asks the LLM for a one-paragraph rollup of the combined text, focused on
   any POIs that were actually detected in this capture (instead of dumping
   every configured POI name into every prompt).
6. Persists an :class:`Analysis` (and a :class:`Transcript` for videos).
7. Best-effort upserts the embedding into ChromaDB.

Every step is wrapped so a single failure (no LLM, no OCR, missing
file) doesn't poison the whole run.

Phase 1-A (v0.10.0) reordered classify → summarize so the prompt only
mentions topics that actually appear in the capture. Pre-classify uses
empty ``summary`` (the skills only need OCR / transcript). When classify
yields no POIs we fall back to the user's top-K most-recently-touched
topics so cross-capture continuity is preserved.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import desc, select

from ..config import RinConfig
from ..llm import make_provider
from ..llm.base import ImageAnalysis, LLMError, Provider, ProviderUnavailable
from ..storage import session, vector_store
from ..storage.models import Analysis, Bucket, Capture, CaptureBucket
from ..storage.models import Transcript as TranscriptModel
from ..utils.logging import get_logger
from . import structured
from .image_analyzer import analyze_image
from .structured import StructuredAnalysis
from .transcribe import Transcript
from .video_analyzer import VideoAnalysis, analyze_video

log = get_logger(__name__)

# Phase 1-A safety net: never let the prompt list more than this many
# POI names regardless of how many were detected or how many topics the
# user has configured.
_MAX_ACTIVE_POIS = 5

# Phase 1-A fallback window: when classify returns no POIs for the
# current capture, look back this many days for the user's recently
# touched topics to preserve cross-capture continuity.
_RECENT_POI_WINDOW_DAYS = 14


def build_summary(
    capture: Capture,
    *,
    image_analyses: list[ImageAnalysis] | None = None,
    video_analyses: list[VideoAnalysis] | None = None,
    provider: Provider | None = None,
    active_pois: list[str] | None = None,
) -> str:
    """Ask the LLM (or fall back) to produce a one-paragraph rollup."""

    image_analyses = image_analyses or []
    video_analyses = video_analyses or []
    text_chunks = _collect_text_chunks(image_analyses, video_analyses)

    if not text_chunks:
        return f"{capture.kind.capitalize()} captured with no extractable text."

    joined = "\n".join(text_chunks)
    if provider is None:
        return _fallback_summary(capture, joined)

    tracked_topics = [poi.strip() for poi in (active_pois or []) if poi and poi.strip()]
    prompt = ""
    if tracked_topics:
        prompt += (
            "This capture touched the following tracked topics: "
            f"{', '.join(tracked_topics)}. Focus your summary on what happened "
            "with them.\n"
        )
    prompt += (
        "You are summarizing a user's screen activity for a personal journal. "
        "Produce a 2-4 sentence paragraph capturing what the user was doing, the "
        "key apps or topics, and any noteworthy items. Do not include filler "
        "phrases. Source material:\n\n" + joined
    )
    try:
        return provider.analyze_text(
            prompt, system="You write concise, factual activity summaries."
        )
    except (LLMError, ProviderUnavailable) as exc:
        log.warning(f"Summary LLM call failed: {exc}")
        return _fallback_summary(capture, joined)


def build_structured_summary(
    capture: Capture,
    *,
    image_analyses: list[ImageAnalysis] | None = None,
    video_analyses: list[VideoAnalysis] | None = None,
    provider: Provider | None = None,
    detected_pois: list[str] | None = None,
    fallback_pois: list[str] | None = None,
    max_poi_blocks: int = 2,
) -> StructuredAnalysis:
    """Phase 1-B: produce general summary + per-POI blocks in one LLM call.

    Falls back to ``StructuredAnalysis(general_summary=build_summary(...,
    active_pois=fallback_pois))`` when:
      * no provider is available,
      * the user didn't trip any tracked POIs (no point asking for blocks),
      * the LLM response failed to parse as JSON,
      * ``max_poi_blocks <= 0`` (disabled).

    ``fallback_pois`` is the Phase 1-A list passed to the plain summary
    prompt when we skip the structured ask (typically the recent-history
    fallback or just the detected list itself).

    The structured payload is intended to be persisted in
    ``Analysis.analysis_json``; ``StructuredAnalysis.general_summary``
    is also written into ``Analysis.summary`` so old readers still work.
    """

    detected_pois = [p for p in (detected_pois or []) if p and p.strip()]
    fallback_pois = fallback_pois if fallback_pois is not None else detected_pois
    image_analyses = image_analyses or []
    video_analyses = video_analyses or []
    text_chunks = _collect_text_chunks(image_analyses, video_analyses)
    if not text_chunks:
        general = f"{capture.kind.capitalize()} captured with no extractable text."
        return StructuredAnalysis(general_summary=general)

    joined = "\n".join(text_chunks)

    # No provider OR no detected POIs OR caller disabled blocks → fall
    # back to plain summary. The general_summary stays in the structured
    # payload so all consumers can read it the same way.
    if provider is None or not detected_pois or max_poi_blocks <= 0:
        general = build_summary(
            capture,
            image_analyses=image_analyses,
            video_analyses=video_analyses,
            provider=provider,
            active_pois=fallback_pois,
        )
        return StructuredAnalysis(general_summary=general)

    prompt = structured.build_prompt(
        detected_pois=detected_pois,
        max_blocks=max_poi_blocks,
        material=joined,
    )
    try:
        reply = provider.analyze_text(
            prompt,
            system=(
                "You produce strict JSON. Reply with ONLY a single JSON object "
                "matching the requested schema."
            ),
        )
    except (LLMError, ProviderUnavailable) as exc:
        log.warning(f"Structured summary LLM call failed: {exc}")
        general = build_summary(
            capture,
            image_analyses=image_analyses,
            video_analyses=video_analyses,
            provider=provider,
            active_pois=fallback_pois,
        )
        return StructuredAnalysis(general_summary=general)

    parsed = structured.parse_llm_response(reply)
    if not parsed.general_summary:
        # The LLM ignored the schema and returned prose; treat the whole
        # response as the general summary.
        log.info(
            "Structured summary: LLM reply was not JSON; using raw text as "
            "general_summary fallback"
        )
        return StructuredAnalysis(general_summary=reply.strip())
    return parsed


def _collect_text_chunks(
    image_analyses: list[ImageAnalysis],
    video_analyses: list[VideoAnalysis],
) -> list[str]:
    text_chunks: list[str] = []
    for ia in image_analyses:
        if ia.summary:
            text_chunks.append(f"- {ia.summary}")
    for va in video_analyses:
        for s in va.frame_summaries:
            text_chunks.append(f"  • {s}")
        if va.transcript.text:
            text_chunks.append(f"Transcript: {va.transcript.text[:1000]}")
        if va.ocr_text:
            text_chunks.append(f"OCR: {va.ocr_text[:500]}")
    return text_chunks


def _fallback_summary(capture: Capture, joined: str) -> str:
    head = joined[:400].replace("\n", " ")
    return f"{capture.kind.capitalize()} captured. Highlights: {head}"


def analyze_capture(
    capture_id: int,
    cfg: RinConfig,
    *,
    provider: Provider | None = None,
    image_analyzer_fn: Callable[..., ImageAnalysis] = analyze_image,
    video_analyzer_fn: Callable[..., VideoAnalysis] = analyze_video,
    embedder: Callable[[str], list[float]] | None = None,
) -> int | None:
    """Analyze one capture. Returns the new ``Analysis.id`` or ``None`` on failure."""

    with session() as s:
        cap = s.get(Capture, capture_id)
        if cap is None:
            log.warning(f"analyze_capture: capture {capture_id} not found")
            return None
        files = [Path(f.path) for f in cap.files]
        kind = cap.kind

    image_analyses: list[ImageAnalysis] = []
    video_analyses: list[VideoAnalysis] = []
    transcript_obj: Transcript | None = None

    if kind == "screenshot":
        for f in files:
            if f.exists():
                image_analyses.append(image_analyzer_fn(f, provider=provider))
    elif kind == "video":
        for f in files:
            if f.exists():
                va = video_analyzer_fn(f, cfg=cfg.analysis, provider=provider)
                video_analyses.append(va)
                if va.transcript.text:
                    transcript_obj = va.transcript

    all_ocr = "\n\n".join(
        [ia.text for ia in image_analyses if ia.text]
        + [va.ocr_text for va in video_analyses if va.ocr_text]
    )
    transcript_text = transcript_obj.text if transcript_obj else ""

    # Phase 1-A: pre-classify BEFORE building the summary so the LLM
    # prompt can list only the topics that actually appear in this
    # capture (not every name in [skills.topic]). classify_capture is
    # wrapped — a crash here must not block the analysis row.
    detected_pois: list[str] = []
    try:
        from ..skills.pipeline import classify_capture

        bucket_ids = classify_capture(
            capture_id,
            cfg,
            summary="",  # not yet built; skills detect from OCR + transcript
            ocr_text=all_ocr,
            transcript=transcript_text,
            provider=provider,
        )
        detected_pois = _topic_pois_from_buckets(bucket_ids)
    except Exception as exc:  # pragma: no cover - defensive boundary
        log.warning(f"Skill classification failed for capture {capture_id}: {exc}")
        bucket_ids = []

    # Phase 1-D (v0.13.0): both the cap and the window are
    # config-driven via [skills] active_top_k and active_window_days.
    active_top_k = max(0, int(getattr(cfg.skills, "active_top_k", _MAX_ACTIVE_POIS)))
    active_window_days = max(
        1, int(getattr(cfg.skills, "active_window_days", _RECENT_POI_WINDOW_DAYS))
    )
    # If this capture didn't trip any topic, prefer the user's recently
    # touched topics so the prompt still has continuity, then cap.
    active_pois = detected_pois or _recent_topic_pois(
        limit=active_top_k, window_days=active_window_days
    )
    active_pois = active_pois[:active_top_k]

    with session() as s:
        cap = s.get(Capture, capture_id)
        if cap is None:
            return None
        # Phase 1-B: ask for a structured payload when we have detected
        # POIs + a provider. Falls back to plain summary otherwise.
        max_blocks = max(0, int(getattr(cfg.analysis, "max_poi_blocks_per_capture", 2)))
        structured_payload = build_structured_summary(
            cap,
            image_analyses=image_analyses,
            video_analyses=video_analyses,
            provider=provider,
            detected_pois=detected_pois,
            fallback_pois=active_pois,
            max_poi_blocks=max_blocks,
        )
        summary = structured_payload.general_summary or _fallback_summary(
            cap, "\n".join(_collect_text_chunks(image_analyses, video_analyses))
        )
        analysis = Analysis(
            capture_id=capture_id,
            summary=summary,
            ocr_text=all_ocr or None,
            entities_json=json.dumps({}),
            analysis_json=structured_payload.to_json(),
            llm_provider=provider.name if provider else None,
            llm_model=getattr(provider, "model", None) if provider else None,
        )
        s.add(analysis)
        if transcript_obj is not None:
            s.add(
                TranscriptModel(
                    capture_id=capture_id,
                    text=transcript_obj.text,
                    language=transcript_obj.language,
                    segments_json=json.dumps(transcript_obj.segments),
                )
            )
        cap.status = "analyzed"
        s.flush()
        analysis_id = analysis.id

    _push_to_index(capture_id, summary + "\n" + all_ocr, embedder)

    log.info(f"Analyzed capture {capture_id} → analysis_id={analysis_id}")
    return analysis_id


def analyze_pending(
    cfg: RinConfig,
    *,
    limit: int = 25,
    provider: Provider | None = None,
    image_analyzer_fn: Callable[..., ImageAnalysis] = analyze_image,
    video_analyzer_fn: Callable[..., VideoAnalysis] = analyze_video,
    embedder: Callable[[str], list[float]] | None = None,
    progress_cb: Callable[[int, int, int], None] | None = None,
) -> list[int]:
    """Find captures without an analysis and process up to ``limit`` of them.

    ``progress_cb`` is invoked once per capture as ``(index, total, capture_id)``
    where ``index`` is 1-based. UI subscribers use it to update a status bar
    or emit toast notifications.
    """

    if provider is None:
        try:
            provider = make_provider(cfg.llm)
        except ProviderUnavailable as exc:
            log.info(f"No LLM provider available: {exc} — using fallback summaries")
            provider = None

    with session() as s:
        pending = (
            s.scalars(
                select(Capture)
                .where(Capture.status == "captured")
                .order_by(Capture.started_at.asc())
                .limit(limit)
            ).all()
        )
        ids = [c.id for c in pending]

    total = len(ids)
    if total == 0:
        log.info("analyze_pending: nothing to do (no 'captured'-status rows)")
        return []

    log.info(f"analyze_pending: starting batch of {total} capture(s)")
    analyzed: list[int] = []
    for idx, cap_id in enumerate(ids, start=1):
        log.info(f"analyze_pending: {idx}/{total} — analyzing capture {cap_id}…")
        try:
            aid = analyze_capture(
                cap_id,
                cfg,
                provider=provider,
                image_analyzer_fn=image_analyzer_fn,
                video_analyzer_fn=video_analyzer_fn,
                embedder=embedder,
            )
            if aid is not None:
                analyzed.append(aid)
        except Exception as exc:
            log.error(f"analyze_capture({cap_id}) crashed: {exc}")
        if progress_cb is not None:
            try:
                progress_cb(idx, total, cap_id)
            except Exception as exc:
                log.warning(f"progress_cb raised: {exc}")
    log.info(f"analyze_pending: finished batch ({len(analyzed)}/{total} succeeded)")
    return analyzed


def _push_to_index(
    capture_id: int,
    text: str,
    embedder: Callable[[str], list[float]] | None,
) -> None:
    """Best-effort push into ChromaDB. Failures are non-fatal.

    Phase 1-C (v0.12.0): metadata now carries ``bucket_keys`` (pipe-padded
    string) and ``bucket_ids_csv`` so :func:`rin.rag.search.search` can
    post-filter by tracked POIs.
    """

    if embedder is None:
        return
    try:
        vec = embedder(text)
    except Exception as exc:
        log.warning(f"Embedding failed for capture {capture_id}: {exc}")
        return
    meta: dict[str, str | int] = {"capture_id": capture_id}
    try:
        from ..rag.indexer import bucket_keys_for_capture, encode_bucket_keys

        bucket_ids, bucket_keys = bucket_keys_for_capture(capture_id)
        if bucket_ids:
            meta["bucket_ids_csv"] = ",".join(str(i) for i in bucket_ids)
            meta["bucket_keys"] = encode_bucket_keys(bucket_keys)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning(f"bucket_keys lookup failed for capture {capture_id}: {exc}")
    try:
        vector_store.upsert(
            collection=vector_store.CAPTURES_COLLECTION,
            ids=[f"cap-{capture_id}"],
            documents=[text[:4000]],
            embeddings=[vec],
            metadatas=[meta],
        )
    except Exception as exc:
        log.warning(f"Vector store upsert failed for capture {capture_id}: {exc}")


def _active_topic_names(cfg: RinConfig) -> list[str]:
    """Return the names of every topic in [skills.topic] when the
    topic skill is enabled. Empty list if disabled or not configured.

    Phase 1-A note: this is no longer used by ``analyze_capture`` (which
    now sources POIs from the classify step and recent-history fallback).
    It is kept for backwards compatibility with external callers and a
    handful of tests.
    """
    if "topic" not in (cfg.skills.enabled or []):
        return []
    raw = cfg.skills.config_for_skill("topic") or {}
    topics = raw.get("topics") or []
    names: list[str] = []
    for t in topics:
        if isinstance(t, dict):
            name = t.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def _topic_pois_from_buckets(bucket_ids: list[int]) -> list[str]:
    """Resolve ``bucket_ids`` (any skill) → ``[title]`` for topic buckets only.

    classify_capture returns ids from every enabled skill; we only want
    topic POIs for the summarizer prompt. Order matches the input order
    so the most-relevant detected POI appears first when truncated.
    """

    if not bucket_ids:
        return []
    with session() as s:
        rows = s.execute(
            select(Bucket.id, Bucket.title).where(
                Bucket.id.in_(bucket_ids),
                Bucket.skill_name == "topic",
            )
        ).all()
    by_id: dict[int, str] = {row.id: (row.title or "").strip() for row in rows}
    out: list[str] = []
    seen: set[str] = set()
    for bid in bucket_ids:
        title = by_id.get(bid)
        if not title or title in seen:
            continue
        seen.add(title)
        out.append(title)
    return out


def _recent_topic_pois(
    *,
    limit: int = _MAX_ACTIVE_POIS,
    window_days: int = _RECENT_POI_WINDOW_DAYS,
) -> list[str]:
    """Top-K topic POIs by most-recent ``CaptureBucket.created_at``.

    Used as the fallback when classify_capture returned no topic
    buckets for the current capture — keeps cross-capture continuity
    without flooding the prompt with every configured topic.

    Phase 1-D (v0.13.0): both ``limit`` and ``window_days`` are now
    driven by ``cfg.skills.active_top_k`` / ``active_window_days`` so
    users can tune the decay envelope. Defaults preserve the v0.10.0
    behavior (5 topics, 14 days).
    """

    if limit <= 0:
        return []
    if window_days <= 0:
        return []
    cutoff = datetime.now() - timedelta(days=window_days)
    with session() as s:
        rows = s.execute(
            select(Bucket.title)
            .join(CaptureBucket, CaptureBucket.bucket_id == Bucket.id)
            .where(
                Bucket.skill_name == "topic",
                CaptureBucket.created_at >= cutoff,
            )
            .order_by(desc(CaptureBucket.created_at))
        ).all()
    out: list[str] = []
    seen: set[str] = set()
    for (title,) in rows:
        clean = (title or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break
    return out

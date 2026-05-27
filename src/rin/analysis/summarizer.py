"""Summarizer: per-capture roll-up + DB write + vector index push.

The summarizer is the analysis pipeline's entry point. It:

1. Loads the capture from the DB.
2. For screenshots, calls :func:`analyze_image` per monitor file.
3. For videos, calls :func:`analyze_video` per file.
4. Asks the LLM for a one-paragraph rollup of the combined text.
5. Persists an :class:`Analysis` (and a :class:`Transcript` for videos).
6. Best-effort upserts the embedding into ChromaDB.

Every step is wrapped so a single failure (no LLM, no OCR, missing
file) doesn't poison the whole run.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from ..config import RinConfig
from ..llm import make_provider
from ..llm.base import ImageAnalysis, LLMError, Provider, ProviderUnavailable
from ..storage import session, vector_store
from ..storage.models import Analysis, Capture
from ..storage.models import Transcript as TranscriptModel
from ..utils.logging import get_logger
from .image_analyzer import analyze_image
from .transcribe import Transcript
from .video_analyzer import VideoAnalysis, analyze_video

log = get_logger(__name__)


def build_summary(
    capture: Capture,
    *,
    image_analyses: list[ImageAnalysis] | None = None,
    video_analyses: list[VideoAnalysis] | None = None,
    provider: Provider | None = None,
) -> str:
    """Ask the LLM (or fall back) to produce a one-paragraph rollup."""

    image_analyses = image_analyses or []
    video_analyses = video_analyses or []
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

    if not text_chunks:
        return f"{capture.kind.capitalize()} captured with no extractable text."

    joined = "\n".join(text_chunks)
    if provider is None:
        return _fallback_summary(capture, joined)

    prompt = (
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

    with session() as s:
        cap = s.get(Capture, capture_id)
        if cap is None:
            return None
        summary = build_summary(
            cap,
            image_analyses=image_analyses,
            video_analyses=video_analyses,
            provider=provider,
        )
        all_ocr = "\n\n".join(
            [ia.text for ia in image_analyses if ia.text]
            + [va.ocr_text for va in video_analyses if va.ocr_text]
        )
        analysis = Analysis(
            capture_id=capture_id,
            summary=summary,
            ocr_text=all_ocr or None,
            entities_json=json.dumps({}),
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
    """Best-effort push into ChromaDB. Failures are non-fatal."""

    if embedder is None:
        return
    try:
        vec = embedder(text)
    except Exception as exc:
        log.warning(f"Embedding failed for capture {capture_id}: {exc}")
        return
    try:
        vector_store.upsert(
            collection=vector_store.CAPTURES_COLLECTION,
            ids=[f"cap-{capture_id}"],
            documents=[text[:4000]],
            embeddings=[vec],
            metadatas=[{"capture_id": capture_id}],
        )
    except Exception as exc:
        log.warning(f"Vector store upsert failed for capture {capture_id}: {exc}")

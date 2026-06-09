"""Connect skill outputs to the analysis pipeline + storage layer."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..config import RinConfig
from ..llm.base import Provider
from ..storage import session
from ..storage.models import Analysis, Bucket, Capture, CaptureBucket, CaptureFile, Transcript
from ..utils.logging import get_logger
from .base import BucketRef, CaptureInfo, Skill, SkillContext
from .registry import LoadedSkill, active_skills

log = get_logger(__name__)


def classify_capture(
    capture_id: int,
    cfg: RinConfig,
    *,
    summary: str,
    ocr_text: str,
    transcript: str = "",
    skills: list[LoadedSkill] | None = None,
    provider: Provider | None = None,
) -> list[int]:
    """Run every enabled skill on ``capture_id`` and upsert bucket links.

    Returns the bucket ids that ``capture_id`` was attached to (may be
    empty when no skill matches or no skills are enabled).

    A skill raising an exception is logged + skipped — one bad skill
    must not break the analysis pipeline.

    ``provider`` is forwarded to any skill exposing ``set_provider`` (the
    bundled ``topic`` skill needs this for its ``llm_judge`` tier). Skills
    that do not expose the method are unaffected.
    """

    if skills is None:
        skills = active_skills(cfg)
    if not skills:
        return []

    if provider is not None:
        for loaded in skills:
            setter = getattr(loaded.skill, "set_provider", None)
            if callable(setter):
                try:
                    setter(provider)
                except Exception as exc:  # noqa: BLE001 - per-skill isolation
                    log.warning(
                        f"Skill {loaded.skill.name!r} set_provider raised: {exc}"
                    )

    # Pull the capture's metadata once (started_at/kind) so each skill
    # gets a frozen SkillContext.
    with session() as s:
        cap = s.get(Capture, capture_id)
        if cap is None:
            log.warning(f"classify_capture: capture {capture_id} not found")
            return []
        started_at = cap.started_at
        kind = cap.kind

    bucket_ids: list[int] = []
    for loaded in skills:
        skill = loaded.skill
        ctx = SkillContext(
            capture_id=capture_id,
            capture_kind=kind,
            started_at=started_at,
            summary=summary or "",
            ocr_text=ocr_text or "",
            transcript_text=transcript or "",
            config=skill.config,
        )
        try:
            refs = list(skill.detect(ctx))
        except Exception as exc:
            log.error(f"Skill {skill.name!r} detect() crashed: {exc}")
            continue
        for ref in refs:
            bucket_id = _upsert_bucket(skill.name, ref)
            _link(capture_id, bucket_id)
            bucket_ids.append(bucket_id)
            log.info(
                f"Skill {skill.name!r} classified cap-{capture_id} into "
                f"bucket {bucket_id} ({ref.key})"
            )
    return bucket_ids


def _upsert_bucket(skill_name: str, ref: BucketRef) -> int:
    """Insert or fetch the ``(skill_name, key)`` bucket; return its id."""

    extra_json = json.dumps(ref.extra) if ref.extra else None
    with session() as s:
        existing = s.scalars(
            select(Bucket).where(
                Bucket.skill_name == skill_name, Bucket.key == ref.key
            )
        ).first()
        if existing is not None:
            # Re-detected — keep the first title but allow extras to merge.
            if ref.extra:
                merged = dict(json.loads(existing.extra_json or "{}"))
                merged.update(ref.extra)
                existing.extra_json = json.dumps(merged)
            return existing.id
        bucket = Bucket(
            skill_name=skill_name,
            key=ref.key,
            title=ref.title,
            extra_json=extra_json,
            status="active",
        )
        s.add(bucket)
        s.flush()
        return bucket.id


def _link(capture_id: int, bucket_id: int) -> None:
    """Insert a (capture_id, bucket_id) row, ignoring duplicates."""

    with session() as s:
        existing = s.get(CaptureBucket, (capture_id, bucket_id))
        if existing is not None:
            return
        s.add(CaptureBucket(capture_id=capture_id, bucket_id=bucket_id))


def load_capture_infos(bucket_id: int) -> list[CaptureInfo]:
    """Load every capture attached to ``bucket_id`` as a
    :class:`CaptureInfo` for the scheduler / archive renderer."""

    with session() as s:
        cap_ids = list(
            s.scalars(
                select(CaptureBucket.capture_id).where(
                    CaptureBucket.bucket_id == bucket_id
                )
            )
        )
        if not cap_ids:
            return []
        rows = (
            s.scalars(
                select(Capture).where(Capture.id.in_(cap_ids)).order_by(
                    Capture.started_at.asc()
                )
            ).all()
        )
        results: list[CaptureInfo] = []
        for c in rows:
            latest_analysis = s.scalars(
                select(Analysis)
                .where(Analysis.capture_id == c.id)
                .order_by(Analysis.created_at.desc())
                .limit(1)
            ).first()
            transcript = s.scalars(
                select(Transcript)
                .where(Transcript.capture_id == c.id)
                .order_by(Transcript.created_at.desc())
                .limit(1)
            ).first()
            files = list(
                s.scalars(
                    select(CaptureFile).where(CaptureFile.capture_id == c.id)
                )
            )
            results.append(
                CaptureInfo(
                    capture_id=c.id,
                    started_at=c.started_at,
                    summary=(latest_analysis.summary if latest_analysis else "") or "",
                    ocr_text=(latest_analysis.ocr_text if latest_analysis else "") or "",
                    transcript_text=(transcript.text if transcript else "") or "",
                    file_paths=tuple(Path(f.path) for f in files),
                )
            )
        return results


def archive_bucket(
    bucket_id: int,
    skill: Skill,
    *,
    provider=None,
    archives_root: Path | None = None,
    now: datetime | None = None,
) -> Path | None:
    """Render the archive Markdown, write it to disk, mark bucket closed.

    Returns the archive path on success, ``None`` if the bucket could
    not be located (caller is responsible for logging that case).
    """

    from ..paths import archives_dir

    now = now or datetime.now()
    archives_root = archives_root or archives_dir()
    captures = load_capture_infos(bucket_id)
    with session() as s:
        bucket = s.get(Bucket, bucket_id)
        if bucket is None:
            return None
        try:
            body = skill.render_archive(bucket, captures, provider=provider)
        except Exception as exc:
            log.error(
                f"Skill {skill.name!r} render_archive crashed for "
                f"bucket {bucket_id}: {exc}"
            )
            # Fall back to the default rollup so we always produce something.
            from .base import _default_archive

            body = _default_archive(bucket, captures)

        out_dir = archives_root / skill.name
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_key = _safe_filename(bucket.key)
        out_path = out_dir / f"{safe_key}.md"
        out_path.write_text(body, encoding="utf-8")

        bucket.status = "archived"
        bucket.closed_at = now
        bucket.archive_path = str(out_path)
    log.info(
        f"Archived bucket {bucket_id} ({skill.name}/{bucket.key}) -> {out_path}"
    )
    return out_path


def _safe_filename(key: str) -> str:
    """Strip path separators + dangerous chars so a malicious bucket key
    cannot escape the archives directory."""

    bad = '<>:"/\\|?*\0'
    out = "".join(("_" if c in bad else c) for c in key.strip())
    return out[:200] or "_unnamed"


__all__ = [
    "archive_bucket",
    "classify_capture",
    "load_capture_infos",
]

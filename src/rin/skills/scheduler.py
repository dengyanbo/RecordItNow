"""Periodic background job: close + archive finished buckets.

Mirrors the pattern used by :class:`rin.analysis.scheduler.AnalysisScheduler`
— APScheduler instance with a non-blocking ``threading.Lock`` so two
ticks cannot run concurrently.
"""
from __future__ import annotations

import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from ..config import RinConfig
from ..llm import make_provider
from ..llm.base import ProviderUnavailable
from ..storage import session
from ..storage.models import Bucket
from ..utils.logging import get_logger
from .pipeline import archive_bucket, load_capture_infos
from .registry import active_skills

log = get_logger(__name__)


class BucketScheduler:
    """Run skill ``should_close`` checks on every active bucket.

    Buckets whose owning skill returns ``True`` are archived through
    :func:`rin.skills.pipeline.archive_bucket`. Manual triggers should
    call :meth:`tick` with ``force=True``.
    """

    def __init__(self, cfg: RinConfig) -> None:
        self.cfg = cfg
        self._scheduler: BackgroundScheduler | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._scheduler is not None:
            return
        if not self.cfg.skills.enabled:
            log.info("BucketScheduler: no skills enabled, scheduler idle")
            return
        hours = max(1, int(self.cfg.skills.closure_check_hours or 6))
        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            self.tick, "interval", hours=hours, id="bucket-tick"
        )
        self._scheduler.start()
        log.info(f"BucketScheduler started (interval={hours}h)")

    def stop(self) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
        finally:
            self._scheduler = None
        log.info("BucketScheduler stopped")

    def tick(self, *, force: bool = False) -> int:
        """Run one closure-check pass. Returns the number of buckets archived.

        ``force`` is only meaningful as documentation today — the lock
        still prevents two overlapping ticks. Manual UI triggers pass
        ``force=True`` for symmetry with :class:`AnalysisScheduler`.
        """

        if not self._lock.acquire(blocking=False):
            log.info("BucketScheduler.tick skipped — another tick still running")
            return 0
        try:
            return self._do_tick(force=force)
        finally:
            self._lock.release()

    # ------------------------------------------------------------------

    def _do_tick(self, *, force: bool) -> int:
        skills = {ls.skill.name: ls.skill for ls in active_skills(self.cfg)}
        if not skills:
            log.debug("BucketScheduler tick: no active skills")
            return 0

        with session() as s:
            buckets = list(
                s.scalars(
                    select(Bucket).where(Bucket.status == "active").order_by(
                        Bucket.opened_at.asc()
                    )
                )
            )
            bucket_ids = [(b.id, b.skill_name) for b in buckets]

        provider = self._safe_provider()
        archived = 0
        now = datetime.now()
        for bucket_id, skill_name in bucket_ids:
            skill = skills.get(skill_name)
            if skill is None:
                # Skill that owned this bucket is no longer enabled — skip
                # but don't archive: user may re-enable it later.
                continue
            captures = load_capture_infos(bucket_id)
            try:
                with session() as s:
                    bucket = s.get(Bucket, bucket_id)
                    if bucket is None:
                        continue
                    should = skill.should_close(bucket, captures, now)
            except Exception as exc:
                log.error(
                    f"Skill {skill_name!r} should_close raised for "
                    f"bucket {bucket_id}: {exc}"
                )
                continue
            if not should:
                continue
            try:
                archive_bucket(bucket_id, skill, provider=provider, now=now)
                archived += 1
            except Exception as exc:
                log.error(
                    f"archive_bucket({bucket_id}) crashed for skill "
                    f"{skill_name!r}: {exc}"
                )
        if archived:
            log.info(f"BucketScheduler tick archived {archived} bucket(s)")
        return archived

    def _safe_provider(self):
        """Best-effort: return an LLM provider, or ``None`` on failure."""

        try:
            return make_provider(self.cfg.llm)
        except ProviderUnavailable as exc:
            log.info(f"BucketScheduler: no LLM provider ({exc}) — archives use fallback")
            return None


__all__ = ["BucketScheduler"]

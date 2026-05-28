"""Skill plugin system — pluggable categorization for captures (v0.5+).

Each :class:`~rin.skills.base.Skill` reads the OCR + LLM summary of a
capture, decides which "buckets" the capture belongs to (e.g. a support
ticket ID), and — when the bucket reaches a "done" state — renders a
Markdown archive summarising the whole journey.

Public entry points:

* :class:`~rin.skills.base.Skill` — the ABC users subclass.
* :class:`~rin.skills.base.BucketRef`,
  :class:`~rin.skills.base.SkillContext`,
  :class:`~rin.skills.base.CaptureInfo` — the lightweight DTOs that
  flow through the pipeline.
* :func:`~rin.skills.registry.discover` — load bundled + user skills.
* :func:`~rin.skills.pipeline.classify_capture` — pipeline hook called
  after each :class:`~rin.storage.models.Analysis` row commits.
* :class:`~rin.skills.scheduler.BucketScheduler` — the periodic job
  that closes and archives finished buckets.
"""
from __future__ import annotations

from .base import BucketRef, CaptureInfo, Skill, SkillContext

__all__ = [
    "BucketRef",
    "CaptureInfo",
    "Skill",
    "SkillContext",
]

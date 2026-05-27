"""Retention policy for raw captures.

Two helpers:

* :func:`compute_purgeable` — pure function that returns the IDs older
  than the cutoff. Easy to unit-test without a real database.
* :func:`purge` — applies the policy: removes capture folders on disk
  and either marks the ``captures`` row as ``purged`` (when
  ``keep_summaries=True``, the default) or deletes the row outright.

Summaries (``analyses`` / ``transcripts`` / vector index) are preserved
by default because they're tiny relative to raw media.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import files as files_mod
from .models import Capture


@dataclass
class PurgeReport:
    capture_ids: list[int]
    folders_removed: list[Path]


def compute_purgeable(
    captures: list[Capture],
    *,
    now: datetime,
    retention_days: int,
) -> list[int]:
    cutoff = now - timedelta(days=retention_days)
    return [c.id for c in captures if c.started_at < cutoff]


def purge(
    db: Session,
    *,
    now: datetime,
    retention_days: int,
    keep_summaries: bool = True,
) -> PurgeReport:
    cutoff = now - timedelta(days=retention_days)
    stmt = select(Capture).where(Capture.started_at < cutoff, Capture.status != "purged")
    folders_removed: list[Path] = []
    purged_ids: list[int] = []
    for cap in db.scalars(stmt):
        if cap.folder:
            folder = Path(cap.folder)
            try:
                files_mod.safe_remove_dir(folder)
                folders_removed.append(folder)
            except ValueError:
                # Folder outside captures root — leave it alone but still update the row.
                pass
        if keep_summaries:
            cap.status = "purged"
            cap.files.clear()
        else:
            db.delete(cap)
        purged_ids.append(cap.id)
    return PurgeReport(capture_ids=purged_ids, folders_removed=folders_removed)

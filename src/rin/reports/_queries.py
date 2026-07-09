"""Private database queries for report generation."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..storage import session
from ..storage.models import (
    Analysis,
    Bucket,
    Capture,
    CaptureBucket,
    CaptureFile,
    Report,
    ReportText,
)


def file_counts(s, cap_ids: list[int]) -> dict[int, int]:
    """Bulk monitor-file counts keyed by capture_id."""

    if not cap_ids:
        return {}
    return dict(
        s.execute(
            select(CaptureFile.capture_id, func.count())
            .where(CaptureFile.capture_id.in_(cap_ids))
            .group_by(CaptureFile.capture_id)
        ).all()
    )


def captures_for_window(start: datetime, end: datetime) -> tuple[list[Capture], dict[int, int]]:
    """Fetch captures and monitor-file counts for a report window."""

    with session() as s:
        rows = (
            s.scalars(
                select(Capture)
                .where(Capture.started_at >= start, Capture.started_at < end)
                .order_by(Capture.started_at.asc(), Capture.id.asc())
                .options(selectinload(Capture.analyses))
            )
            .unique()
            .all()
        )
        counts = file_counts(s, [c.id for c in rows])
    return rows, counts


def bucket_capture_rows_for_window(
    start: datetime, end: datetime
) -> tuple[list[tuple[Bucket, Capture]], dict[int, int]]:
    """Fetch bucket/capture pairs that touched a report window."""

    with session() as s:
        rows = s.execute(
            select(Bucket, Capture)
            .join(CaptureBucket, CaptureBucket.bucket_id == Bucket.id)
            .join(Capture, Capture.id == CaptureBucket.capture_id)
            .where(Capture.started_at >= start, Capture.started_at < end)
            .order_by(
                Bucket.opened_at.asc(),
                Bucket.id.asc(),
                Capture.started_at.asc(),
                Capture.id.asc(),
            )
            .options(selectinload(Capture.analyses))
        ).all()
        counts = file_counts(s, [capture.id for _bucket, capture in rows])
    return rows, counts


def uncategorized_captures_for_window(
    start: datetime, end: datetime
) -> tuple[list[Capture], dict[int, int]]:
    """Fetch captures in a report window with no capture_bucket rows."""

    with session() as s:
        rows = (
            s.scalars(
                select(Capture)
                .outerjoin(CaptureBucket, CaptureBucket.capture_id == Capture.id)
                .where(Capture.started_at >= start, Capture.started_at < end)
                .where(CaptureBucket.capture_id.is_(None))
                .order_by(Capture.started_at.asc(), Capture.id.asc())
                .options(selectinload(Capture.analyses))
            )
            .unique()
            .all()
        )
        counts = file_counts(s, [c.id for c in rows])
    return rows, counts


def load_cached_narratives(
    kind: str,
    period_start: datetime,
    period_end: datetime,
) -> tuple[int | None, dict[str, str]]:
    """Fetch the existing report row (if any) plus cached PoI narratives."""

    with session() as s:
        row = s.scalars(
            select(Report).where(
                Report.kind == kind,
                Report.period_start == period_start,
                Report.period_end == period_end,
            )
        ).first()
        if row is None:
            return None, {}
        report_id = row.id
        raw = row.poi_narratives_json
    if not raw:
        return report_id, {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return report_id, {}
    if not isinstance(data, dict):
        return report_id, {}
    return report_id, {str(k): str(v) for k, v in data.items() if v}


def persist_poi_narratives(report_id: int, narratives: dict[str, str]) -> None:
    """Persist the per-bucket narrative cache for an existing report."""

    with session() as s:
        row = s.get(Report, report_id)
        if row is None:
            return
        if not narratives:
            row.poi_narratives_json = None
        else:
            row.poi_narratives_json = json.dumps(narratives, ensure_ascii=False)


def upsert_report_text(
    *,
    kind: str,
    period_start: datetime,
    period_end: datetime,
    markdown_path: Path,
    body: str,
) -> int:
    """Insert or update the Report and ReportText rows, returning report id."""

    with session() as s:
        existing = s.scalars(
            select(Report).where(
                Report.kind == kind,
                Report.period_start == period_start,
                Report.period_end == period_end,
            )
        ).first()
        if existing is not None:
            existing.markdown_path = str(markdown_path)
            report = existing
        else:
            report = Report(
                kind=kind,
                period_start=period_start,
                period_end=period_end,
                markdown_path=str(markdown_path),
            )
            s.add(report)
        s.flush()
        report_id = report.id
        report_text = s.get(ReportText, report_id)
        if report_text is None:
            s.add(ReportText(report_id=report_id, body_text=body))
        else:
            report_text.body_text = body
        return report_id


def analyses_for_capture(cap_id: int) -> list[Analysis]:
    """Fetch analyses for a capture."""

    with session() as s:
        return list(s.scalars(select(Analysis).where(Analysis.capture_id == cap_id)).all())

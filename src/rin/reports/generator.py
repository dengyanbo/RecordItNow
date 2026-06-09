"""Report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..analysis import structured as structured_summary
from ..config import RinConfig
from ..llm import make_provider
from ..llm.base import LLMError, Provider, ProviderUnavailable
from ..paths import reports_dir
from ..storage import session
from ..storage.models import (
    Analysis,
    Bucket,
    Capture,
    CaptureBucket,
    Report,
    ReportText,
)
from ..utils.logging import get_logger
from .integrations.base import CalendarEvent
from .integrations.factory import make_calendar_provider
from .templates import (
    FALLBACK_REPORT_TEMPLATE,
    LLM_PROMPT_TEMPLATE,
    POI_GROUPED_LLM_PROMPT,
    POI_GROUPED_REPORT_TEMPLATE,
)

log = get_logger(__name__)

ReportKind = Literal["daily", "weekly", "custom"]


@dataclass
class ReportPeriod:
    kind: ReportKind
    start: datetime
    end: datetime


@dataclass
class CaptureItem:
    id: int
    kind: str
    started_at: datetime
    duration_ms: int | None
    monitor_count: int
    summary: str | None = None
    # Phase 1-B (v0.11.0): per-POI block text keyed by lowercased POI name.
    # Populated from ``analyses.analysis_json``. Used by the per-POI report
    # layout to substitute the topic-specific block for the general summary
    # inside its section. Empty dict for old analyses or chronological view.
    poi_blocks: dict[str, str] = field(default_factory=dict)


@dataclass
class PoIReportSection:
    """One per-topic section of a PoI-grouped report."""

    bucket_id: int
    title: str
    status_change: str | None
    captures: list[CaptureItem]
    archive_path: str | None
    # Phase 1-C (v0.12.0): 2-3 sentence cross-capture narrative for this
    # topic in the report's period. ``None`` means we haven't generated
    # one (insufficient captures, no provider, or LLM call failed).
    narrative: str | None = None


def _capture_item_from_capture(capture: Capture) -> CaptureItem:
    latest = capture.analyses[-1] if capture.analyses else None
    summary = latest.summary if latest else None
    blocks: dict[str, str] = {}
    if latest is not None:
        parsed = structured_summary.parse(latest.analysis_json)
        for b in parsed.poi_blocks:
            blocks[b.poi.strip().lower()] = b.block
    return CaptureItem(
        id=capture.id,
        kind=capture.kind,
        started_at=capture.started_at,
        duration_ms=capture.duration_ms,
        monitor_count=len(capture.files),
        summary=summary,
        poi_blocks=blocks,
    )


def _capture_item_for_section(capture: Capture, section_title: str) -> CaptureItem:
    """Like :func:`_capture_item_from_capture` but substitutes the POI-
    specific block for ``summary`` when available, so templates can render
    the topic-specific narrative inside each section without changes."""

    item = _capture_item_from_capture(capture)
    block = item.poi_blocks.get(section_title.strip().lower())
    if block:
        item.summary = block
    return item


@dataclass
class GeneratedReport:
    report_id: int
    path: Path
    body: str
    period: ReportPeriod
    items: list[CaptureItem] = field(default_factory=list)


def daily_period(now: datetime | None = None) -> ReportPeriod:
    """Yesterday 00:00 → today 00:00."""

    now = now or datetime.now()
    end = datetime.combine(now.date(), time.min)
    start = end - timedelta(days=1)
    return ReportPeriod(kind="daily", start=start, end=end)


def weekly_period(now: datetime | None = None) -> ReportPeriod:
    """Previous full ISO week (Mon 00:00 → next Mon 00:00)."""

    now = now or datetime.now()
    today = datetime.combine(now.date(), time.min)
    end = today - timedelta(days=today.weekday())
    start = end - timedelta(days=7)
    return ReportPeriod(kind="weekly", start=start, end=end)


def list_captures_for_period(period: ReportPeriod) -> list[CaptureItem]:
    with session() as s:
        rows = (
            s.scalars(
                select(Capture)
                .where(Capture.started_at >= period.start, Capture.started_at < period.end)
                .order_by(Capture.started_at.asc(), Capture.id.asc())
                .options(selectinload(Capture.analyses), selectinload(Capture.files))
            )
            .unique()
            .all()
        )
    return [_capture_item_from_capture(capture) for capture in rows]


def _bucket_status_change(bucket: Bucket, period: ReportPeriod) -> str | None:
    opened_in_period = period.start <= bucket.opened_at < period.end
    closed_in_period = (
        bucket.closed_at is not None and period.start <= bucket.closed_at < period.end
    )
    if opened_in_period and closed_in_period:
        return "opened and archived in period"
    if opened_in_period:
        return "opened in period"
    if closed_in_period:
        return "archived in period"
    return None


def list_poi_sections_for_period(period: ReportPeriod) -> list[PoIReportSection]:
    """Load every bucket that touched the period.

    A bucket is considered touched when it has at least one linked capture in the
    report window. Sections are sorted by ``bucket.opened_at`` ascending.
    """

    with session() as s:
        rows = s.execute(
            select(Bucket, Capture)
            .join(CaptureBucket, CaptureBucket.bucket_id == Bucket.id)
            .join(Capture, Capture.id == CaptureBucket.capture_id)
            .where(Capture.started_at >= period.start, Capture.started_at < period.end)
            .order_by(
                Bucket.opened_at.asc(),
                Bucket.id.asc(),
                Capture.started_at.asc(),
                Capture.id.asc(),
            )
            .options(selectinload(Capture.analyses), selectinload(Capture.files))
        ).all()

    sections_by_bucket: dict[int, PoIReportSection] = {}
    ordered_bucket_ids: list[int] = []
    for bucket, capture in rows:
        section = sections_by_bucket.get(bucket.id)
        if section is None:
            section = PoIReportSection(
                bucket_id=bucket.id,
                title=bucket.title,
                status_change=_bucket_status_change(bucket, period),
                captures=[],
                archive_path=bucket.archive_path,
            )
            sections_by_bucket[bucket.id] = section
            ordered_bucket_ids.append(bucket.id)
        section.captures.append(_capture_item_for_section(capture, bucket.title))

    return [sections_by_bucket[bucket_id] for bucket_id in ordered_bucket_ids]


def list_uncategorized_captures_for_period(period: ReportPeriod) -> list[CaptureItem]:
    """Captures in period that have zero rows in ``capture_buckets``."""

    with session() as s:
        rows = (
            s.scalars(
                select(Capture)
                .outerjoin(CaptureBucket, CaptureBucket.capture_id == Capture.id)
                .where(Capture.started_at >= period.start, Capture.started_at < period.end)
                .where(CaptureBucket.capture_id.is_(None))
                .order_by(Capture.started_at.asc(), Capture.id.asc())
                .options(selectinload(Capture.analyses), selectinload(Capture.files))
            )
            .unique()
            .all()
        )
    return [_capture_item_from_capture(capture) for capture in rows]


def _resolve_layout(cfg: RinConfig, sections: list[PoIReportSection]) -> str:
    layout = cfg.reports.layout
    if layout == "auto":
        return "per_poi" if sections else "chronological"
    return layout


# Phase 1-C (v0.12.0) — per-POI narrative paragraphs.
# Sections with this many captures qualify for an LLM-generated narrative.
POI_NARRATIVE_MIN_CAPTURES = 3

POI_NARRATIVE_PROMPT = (
    "Write a single 2-3 sentence paragraph that tells the cross-capture "
    "story of the topic \"{topic}\" during the {kind} report period "
    "({period_start} → {period_end}). Reference capture IDs like cap-12 "
    "when useful. Be factual; do not invent details that aren't in the "
    "source material.\n\n"
    "Captures (chronological):\n{material}\n"
)


def _build_narrative_prompt(
    section: PoIReportSection, period: ReportPeriod
) -> str:
    material_lines: list[str] = []
    for cap in section.captures:
        material_lines.append(
            f"- cap-{cap.id} @ "
            f"{cap.started_at.strftime('%Y-%m-%d %H:%M')} — "
            f"{(cap.summary or '(no summary)')[:500]}"
        )
    return POI_NARRATIVE_PROMPT.format(
        topic=section.title,
        kind=period.kind,
        period_start=period.start.strftime("%Y-%m-%d %H:%M"),
        period_end=period.end.strftime("%Y-%m-%d %H:%M"),
        material="\n".join(material_lines) or "(none)",
    )


def _load_cached_narratives(
    period: ReportPeriod,
) -> tuple[int | None, dict[str, str]]:
    """Fetch the existing Report row (if any) plus its cached narratives.

    Returns ``(report_id, {bucket_id_str: narrative})``. The cache key is the
    bucket id as a string so it round-trips through JSON safely.
    """

    import json as _json

    with session() as s:
        row = s.scalars(
            select(Report).where(
                Report.kind == period.kind,
                Report.period_start == period.start,
                Report.period_end == period.end,
            )
        ).first()
        if row is None:
            return None, {}
        report_id = row.id
        raw = row.poi_narratives_json
    if not raw:
        return report_id, {}
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return report_id, {}
    if not isinstance(data, dict):
        return report_id, {}
    return report_id, {str(k): str(v) for k, v in data.items() if v}


def populate_poi_narratives(
    period: ReportPeriod,
    sections: list[PoIReportSection],
    *,
    provider: Provider | None,
    min_captures: int = POI_NARRATIVE_MIN_CAPTURES,
    cache: dict[str, str] | None = None,
) -> dict[str, str]:
    """Attach ``section.narrative`` for every section qualifying for one.

    Returns the merged ``{bucket_id_str: narrative}`` cache (existing
    cache entries preserved; new ones added) so the caller can persist
    it on the Report row.
    """

    merged: dict[str, str] = dict(cache or {})
    for section in sections:
        bucket_key = str(section.bucket_id)
        cached = merged.get(bucket_key)
        if cached:
            section.narrative = cached
            continue
        if provider is None or len(section.captures) < min_captures:
            continue
        prompt = _build_narrative_prompt(section, period)
        try:
            narrative = provider.analyze_text(
                prompt,
                system=(
                    "You write a concise factual paragraph for an "
                    "activity report. No fluff."
                ),
            )
        except LLMError as exc:
            log.warning(
                f"POI narrative LLM call failed for bucket {section.bucket_id}: {exc}"
            )
            continue
        narrative = (narrative or "").strip()
        if not narrative:
            continue
        section.narrative = narrative
        merged[bucket_key] = narrative
    return merged


def _persist_poi_narratives(report_id: int, narratives: dict[str, str]) -> None:
    import json as _json

    with session() as s:
        row = s.get(Report, report_id)
        if row is None:
            return
        if not narratives:
            row.poi_narratives_json = None
        else:
            row.poi_narratives_json = _json.dumps(narratives, ensure_ascii=False)


def generate_report(
    period: ReportPeriod,
    cfg: RinConfig,
    *,
    items: list[CaptureItem] | None = None,
    provider: Provider | None = None,
    out_dir: Path | None = None,
) -> GeneratedReport:
    """Render and persist a report. Returns the saved markdown path."""

    items = items if items is not None else list_captures_for_period(period)
    poi_sections = (
        list_poi_sections_for_period(period)
        if cfg.reports.layout != "chronological"
        else []
    )
    layout = _resolve_layout(cfg, poi_sections)
    if provider is None:
        try:
            provider = make_provider(cfg.llm)
        except ProviderUnavailable:
            provider = None

    if layout == "per_poi":
        uncategorized = list_uncategorized_captures_for_period(period)
        _existing_report_id, cached_narratives = _load_cached_narratives(period)
        narratives = populate_poi_narratives(
            period,
            poi_sections,
            provider=provider,
            cache=cached_narratives,
        )
        body = _render_poi_grouped_body(
            period,
            items,
            poi_sections,
            uncategorized,
            provider=provider,
        )
    else:
        narratives = {}
        body = _render_body(period, items, provider=provider, cfg=cfg)
    out_dir = out_dir or reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{period.kind}-{period.start.strftime('%Y%m%d')}.md"
    path = out_dir / filename
    path.write_text(body, encoding="utf-8")

    with session() as s:
        existing = s.scalars(
            select(Report).where(
                Report.kind == period.kind,
                Report.period_start == period.start,
                Report.period_end == period.end,
            )
        ).first()
        if existing is not None:
            existing.markdown_path = str(path)
            report = existing
        else:
            report = Report(
                kind=period.kind,
                period_start=period.start,
                period_end=period.end,
                markdown_path=str(path),
            )
            s.add(report)
        s.flush()
        report_id = report.id
        report_text = s.get(ReportText, report_id)
        if report_text is None:
            s.add(ReportText(report_id=report_id, body_text=body))
        else:
            report_text.body_text = body

    if layout == "per_poi":
        _persist_poi_narratives(report_id, narratives)

    _maybe_write_obsidian_copy(period, body, len(items), cfg)
    log.info(f"Generated {period.kind} report → {path}")
    return GeneratedReport(
        report_id=report_id, path=path, body=body, period=period, items=items
    )


def _maybe_write_obsidian_copy(
    period: ReportPeriod,
    body: str,
    capture_count: int,
    cfg: RinConfig,
) -> None:
    vault_root = (cfg.reports.obsidian_vault_path or "").strip()
    if not vault_root:
        return
    folder_name = {
        "daily": "Daily",
        "weekly": "Weekly",
    }.get(period.kind, period.kind.capitalize())
    vault_path = Path(vault_root) / folder_name / f"{period.start.date().isoformat()}.md"
    payload = _obsidian_front_matter(period, capture_count) + body
    try:
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        vault_path.write_text(payload, encoding="utf-8")
        log.info(f"Wrote Obsidian {period.kind} report copy → {vault_path}")
    except OSError as exc:
        log.warning(f"Could not write Obsidian report copy to {vault_path}: {exc}")


def _obsidian_front_matter(period: ReportPeriod, capture_count: int) -> str:
    return (
        "---\n"
        f"date: {period.start.date().isoformat()}\n"
        f"kind: {period.kind}\n"
        f"captures: {capture_count}\n"
        "generated_by: RIN\n"
        "---\n\n"
    )


def _render_body(
    period: ReportPeriod,
    items: list[CaptureItem],
    *,
    provider: Provider | None,
    cfg: RinConfig,
) -> str:
    if provider is None or not items:
        return _render_offline(period, items)
    material = _format_material(items)
    calendar_material = _calendar_material(period, cfg)
    if calendar_material:
        material = f"{material}\n\n{calendar_material}"
    prompt = LLM_PROMPT_TEMPLATE.format(
        kind=period.kind,
        period_start=period.start.strftime("%Y-%m-%d %H:%M"),
        period_end=period.end.strftime("%Y-%m-%d %H:%M"),
        material=material,
    )
    try:
        return provider.analyze_text(
            prompt,
            system="You write concise markdown personal-activity reports.",
        )
    except LLMError as exc:
        log.warning(f"Report LLM call failed; using offline template: {exc}")
        return _render_offline(period, items)


def _render_poi_grouped_body(
    period: ReportPeriod,
    items: list[CaptureItem],
    poi_sections: list[PoIReportSection],
    uncategorized: list[CaptureItem],
    *,
    provider: Provider | None,
) -> str:
    if provider is None or not items:
        return _render_poi_grouped_offline(period, items, poi_sections, uncategorized)
    prompt = POI_GROUPED_LLM_PROMPT.format(
        kind=period.kind,
        kind_title=period.kind.capitalize(),
        period_start=period.start.strftime("%Y-%m-%d %H:%M"),
        period_end=period.end.strftime("%Y-%m-%d %H:%M"),
        total_captures=len(items),
        topic_count=len(poi_sections),
        material=_format_poi_material(poi_sections, uncategorized),
    )
    try:
        return provider.analyze_text(
            prompt,
            system="You write concise markdown personal-activity reports.",
        )
    except LLMError as exc:
        log.warning(f"Per-PoI report LLM call failed; using offline template: {exc}")
        return _render_poi_grouped_offline(period, items, poi_sections, uncategorized)



def _render_poi_grouped_offline(
    period: ReportPeriod,
    items: list[CaptureItem],
    poi_sections: list[PoIReportSection],
    uncategorized: list[CaptureItem],
) -> str:
    try:
        from jinja2 import Template
    except ImportError:  # pragma: no cover
        return _render_poi_grouped_offline_plain(
            period,
            items,
            poi_sections,
            uncategorized,
        )
    tmpl = Template(POI_GROUPED_REPORT_TEMPLATE)
    return tmpl.render(
        kind=period.kind,
        period_start=period.start,
        period_end=period.end,
        items=items,
        poi_sections=poi_sections,
        uncategorized=uncategorized,
    )



def _render_offline(period: ReportPeriod, items: list[CaptureItem]) -> str:
    try:
        from jinja2 import Template
    except ImportError:  # pragma: no cover
        return _render_offline_plain(period, items)
    tmpl = Template(FALLBACK_REPORT_TEMPLATE)
    return tmpl.render(
        kind=period.kind,
        period_start=period.start,
        period_end=period.end,
        items=items,
    )


def _render_offline_plain(period: ReportPeriod, items: list[CaptureItem]) -> str:
    lines = [
        f"# RIN Report — {period.kind.capitalize()}",
        "",
        f"**Period:** {period.start.isoformat()} → {period.end.isoformat()}",
        f"**Captures:** {len(items)}",
        "",
    ]
    for it in items:
        lines.append(
            f"- cap-{it.id} {it.kind} @ {it.started_at.isoformat()} — {it.summary or '(no summary)'}"
        )
    return "\n".join(lines)



def _render_poi_grouped_offline_plain(
    period: ReportPeriod,
    items: list[CaptureItem],
    poi_sections: list[PoIReportSection],
    uncategorized: list[CaptureItem],
) -> str:
    lines = [
        f"# RIN Report — {period.kind.capitalize()}",
        "",
        f"**Period:** {period.start.isoformat()} → {period.end.isoformat()}",
        "",
        f"**Captures in range:** {len(items)}",
        f"**Topics active in period:** {len(poi_sections)}",
        "",
    ]
    for section in poi_sections:
        lines.append(f"## {section.title}")
        lines.append("")
        if section.status_change:
            lines.append(f"**Status:** {section.status_change}")
        lines.append(f"**Captures in period:** {len(section.captures)}")
        if section.archive_path:
            lines.append(f"**Archive:** {section.archive_path}")
        lines.append("")
        if section.narrative:
            lines.append(section.narrative)
            lines.append("")
        for capture in section.captures:
            lines.append(
                f"- cap-{capture.id} @ {capture.started_at.isoformat()} — "
                f"{capture.summary or '(no summary)'}"
            )
        lines.append("")
    if uncategorized:
        lines.append("## Uncategorized")
        lines.append("")
        for capture in uncategorized:
            lines.append(
                f"- cap-{capture.id} @ {capture.started_at.isoformat()} — "
                f"{capture.summary or '(no summary)'}"
            )
    else:
        lines.append("_All captures were categorized into a topic._")
    lines.extend(["", "---", "", "_Generated offline (no LLM provider available)._"])
    return "\n".join(lines)


def _calendar_material(period: ReportPeriod, cfg: RinConfig) -> str:
    calendar_provider = make_calendar_provider(cfg)
    if calendar_provider is None:
        return ""
    try:
        events = calendar_provider.fetch_events(period.start, period.end)
    except Exception as exc:
        log.warning(f"Calendar fetch failed; continuing without calendar context: {exc}")
        return ""
    if not events:
        return ""
    lines = ["## Calendar", ""]
    for event in events:
        details = []
        if event.organizer:
            details.append(f"organizer: {event.organizer}")
        if event.location:
            details.append(f"location: {event.location}")
        suffix = f" ({'; '.join(details)})" if details else ""
        lines.append(
            "- "
            f"{_format_calendar_range(event)}: {event.subject}{suffix}"
        )
    return "\n".join(lines)


def _format_calendar_range(event: CalendarEvent) -> str:
    if event.start.date() == event.end.date():
        return (
            f"{event.start.strftime('%Y-%m-%d %H:%M')}"
            f" → {event.end.strftime('%H:%M')}"
        )
    return (
        f"{event.start.strftime('%Y-%m-%d %H:%M')}"
        f" → {event.end.strftime('%Y-%m-%d %H:%M')}"
    )


def _format_material(items: list[CaptureItem]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"- cap-{it.id} {it.kind} @ {it.started_at.isoformat()}: "
            f"{(it.summary or '(no summary)')[:600]}"
        )
    return "\n".join(lines)



def _format_poi_material(
    poi_sections: list[PoIReportSection],
    uncategorized: list[CaptureItem],
) -> str:
    lines = []
    for section in poi_sections:
        lines.append(f"TOPIC: {section.title}")
        if section.status_change:
            lines.append(f"  Status: {section.status_change}")
        if section.archive_path:
            lines.append(f"  Archive: {section.archive_path}")
        if section.narrative:
            lines.append(f"  Narrative: {section.narrative}")
        lines.append("  Captures in period:")
        for capture in section.captures:
            lines.append(
                f"    cap-{capture.id} @ "
                f"{capture.started_at.strftime('%Y-%m-%d %H:%M')} — "
                f"{(capture.summary or '(no summary)')[:600]}"
            )
        lines.append("")
    if uncategorized:
        lines.append("UNCATEGORIZED:")
        for capture in uncategorized:
            lines.append(
                f"  cap-{capture.id} @ "
                f"{capture.started_at.strftime('%Y-%m-%d %H:%M')} — "
                f"{(capture.summary or '(no summary)')[:600]}"
            )
    return "\n".join(lines).strip()



def _orm_analyses_for(_cap_id: int) -> list[Analysis]:  # pragma: no cover - convenience helper
    with session() as s:
        return list(s.scalars(select(Analysis).where(Analysis.capture_id == _cap_id)).all())

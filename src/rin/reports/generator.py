"""Report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import RinConfig
from ..llm import make_provider
from ..llm.base import LLMError, Provider, ProviderUnavailable
from ..paths import reports_dir
from ..storage import session
from ..storage.models import Analysis, Capture, Report, ReportText
from ..utils.logging import get_logger
from .templates import FALLBACK_REPORT_TEMPLATE, LLM_PROMPT_TEMPLATE

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
                .order_by(Capture.started_at.asc())
                .options(selectinload(Capture.analyses), selectinload(Capture.files))
            ).unique().all()
        )
        return [
            CaptureItem(
                id=c.id,
                kind=c.kind,
                started_at=c.started_at,
                duration_ms=c.duration_ms,
                monitor_count=len(c.files),
                summary=(c.analyses[-1].summary if c.analyses else None),
            )
            for c in rows
        ]


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
    if provider is None:
        try:
            provider = make_provider(cfg.llm)
        except ProviderUnavailable:
            provider = None

    body = _render_body(period, items, provider=provider)
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
) -> str:
    if provider is None or not items:
        return _render_offline(period, items)
    material = _format_material(items)
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


def _format_material(items: list[CaptureItem]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"- cap-{it.id} {it.kind} @ {it.started_at.isoformat()}: "
            f"{(it.summary or '(no summary)')[:600]}"
        )
    return "\n".join(lines)


def _orm_analyses_for(_cap_id: int) -> list[Analysis]:  # pragma: no cover - convenience helper
    with session() as s:
        return list(s.scalars(select(Analysis).where(Analysis.capture_id == _cap_id)).all())

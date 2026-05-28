"""Full-text search across generated reports."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..storage import session
from ..storage.models import Report, ReportText

_SEARCH_SQL = text(
    """
    SELECT
        r.id AS report_id,
        r.period_start AS period_start,
        r.kind AS kind,
        rt.body AS body,
        bm25(reports_fts) AS rank
    FROM reports_fts
    JOIN report_text AS rt ON rt.report_id = reports_fts.rowid
    JOIN reports AS r ON r.id = rt.report_id
    WHERE reports_fts MATCH :query
    ORDER BY rank, r.period_start DESC
    LIMIT :limit
    """
)

_QUERY_TERM_RE = re.compile(r'"([^"]+)"|(\w+)')


@dataclass(slots=True)
class ReportHit:
    report_id: int
    period_start: datetime
    kind: str
    snippet: str
    rank: float


def search_reports(query: str, limit: int = 20) -> list[ReportHit]:
    """Search report bodies with SQLite FTS5 and return ranked hits."""

    if sqlite3.sqlite_version_info < (3, 9, 0):
        return []
    query = query.strip()
    if not query:
        return []
    with session() as s:
        _sync_report_text_cache(s)
        rows = _run_search_query(s, query, limit=max(1, limit))
    return [
        ReportHit(
            report_id=int(row["report_id"]),
            period_start=_coerce_period_start(row["period_start"]),
            kind=str(row["kind"]),
            snippet=_extract_snippet(str(row["body"]), query),
            rank=float(row["rank"]),
        )
        for row in rows
    ]


def _run_search_query(s: Session, query: str, *, limit: int) -> list[dict]:
    params = {"query": query, "limit": limit}
    try:
        return [dict(row) for row in s.execute(_SEARCH_SQL, params).mappings().all()]
    except SQLAlchemyError:
        fallback = _quote_as_phrase(query)
        if fallback == query:
            return []
        return [dict(row) for row in s.execute(_SEARCH_SQL, {"query": fallback, "limit": limit}).mappings().all()]


def _sync_report_text_cache(s: Session) -> None:
    changed = False
    reports = s.scalars(select(Report).order_by(Report.id.asc())).all()
    for report in reports:
        try:
            body = Path(report.markdown_path).read_text(encoding="utf-8")
        except OSError:
            continue
        cached = s.get(ReportText, report.id)
        if cached is None:
            s.add(ReportText(report_id=report.id, body_text=body))
            changed = True
        elif cached.body_text != body:
            cached.body_text = body
            changed = True
    if changed:
        s.flush()


def _coerce_period_start(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _extract_snippet(body: str, query: str, *, width: int = 240) -> str:
    if len(body) <= width:
        return body.strip()
    lowered = body.lower()
    match_at = None
    for term in _query_terms(query):
        idx = lowered.find(term.lower())
        if idx != -1 and (match_at is None or idx < match_at):
            match_at = idx
    if match_at is None:
        match_at = 0
    start = max(0, match_at - (width // 2))
    end = min(len(body), start + width)
    start = max(0, end - width)
    snippet = body[start:end].strip()
    if start > 0:
        snippet = "…" + snippet.lstrip()
    if end < len(body):
        snippet = snippet.rstrip() + "…"
    return snippet


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for phrase, word in _QUERY_TERM_RE.findall(query):
        token = phrase or word
        if not token:
            continue
        if word and word.upper() in {"AND", "OR", "NOT", "NEAR"}:
            continue
        terms.append(token)
    return terms


def _quote_as_phrase(query: str) -> str:
    escaped = query.replace('"', '""').strip()
    if not escaped:
        return query
    return f'"{escaped}"'

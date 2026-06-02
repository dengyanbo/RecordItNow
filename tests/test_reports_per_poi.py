"""PoI-grouped report generator tests."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from jinja2 import Template

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.reports.generator import (
    CaptureItem,
    PoIReportSection,
    ReportPeriod,
    _resolve_layout,
    generate_report,
    list_poi_sections_for_period,
    list_uncategorized_captures_for_period,
)
from rin.reports.templates import POI_GROUPED_REPORT_TEMPLATE
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Bucket, Capture, CaptureBucket
from rin.utils.logging import get_logger

log = get_logger(__name__)


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()



def _period() -> ReportPeriod:
    return ReportPeriod(
        kind="daily",
        start=datetime(2026, 5, 20, 0, 0),
        end=datetime(2026, 5, 21, 0, 0),
    )



def _insert_capture(
    when: datetime,
    summary: str,
    *,
    kind: str = "screenshot",
) -> int:
    with session() as s:
        cap = Capture(kind=kind, status="analyzed", started_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=summary))
        s.flush()
        return cap.id



def _insert_bucket(
    title: str,
    *,
    opened_at: datetime,
    closed_at: datetime | None = None,
    archive_path: str | None = None,
    status: str = "active",
) -> int:
    with session() as s:
        bucket = Bucket(
            skill_name="topic",
            key=title,
            title=title,
            status=status,
            opened_at=opened_at,
            closed_at=closed_at,
            archive_path=archive_path,
        )
        s.add(bucket)
        s.flush()
        return bucket.id



def _link_capture(bucket_id: int, capture_id: int) -> None:
    with session() as s:
        s.add(CaptureBucket(bucket_id=bucket_id, capture_id=capture_id))
        s.flush()



def _sample_capture_item(cap_id: int = 1, summary: str = "Worked on topic") -> CaptureItem:
    return CaptureItem(
        id=cap_id,
        kind="screenshot",
        started_at=datetime(2026, 5, 20, 9, 0),
        duration_ms=1_000,
        monitor_count=1,
        summary=summary,
    )



def _sample_section() -> PoIReportSection:
    return PoIReportSection(
        bucket_id=1,
        title="MyTopic",
        status_change=None,
        captures=[_sample_capture_item()],
        archive_path=None,
    )



def test_list_poi_sections_returns_empty_when_no_buckets(rin_db: Path) -> None:
    assert list_poi_sections_for_period(_period()) == []



def test_list_poi_sections_includes_buckets_with_captures_in_period(rin_db: Path) -> None:
    period = _period()
    bucket_id = _insert_bucket("Project Atlas", opened_at=datetime(2026, 5, 1, 9, 0))
    first = _insert_capture(datetime(2026, 5, 20, 9, 0), "Kickoff sync")
    second = _insert_capture(datetime(2026, 5, 20, 15, 0), "Reviewed API plan")
    outside = _insert_capture(datetime(2026, 5, 19, 18, 0), "Earlier context")

    _link_capture(bucket_id, first)
    _link_capture(bucket_id, second)
    _link_capture(bucket_id, outside)

    sections = list_poi_sections_for_period(period)

    assert len(sections) == 1
    assert sections[0].title == "Project Atlas"
    assert [cap.id for cap in sections[0].captures] == [first, second]



def test_list_poi_sections_status_change_archived_in_period(rin_db: Path) -> None:
    period = _period()
    bucket_id = _insert_bucket(
        "INC0099999",
        opened_at=datetime(2026, 5, 1, 9, 0),
        closed_at=datetime(2026, 5, 20, 16, 0),
        archive_path="reports\\archives\\topic\\INC0099999.md",
        status="archived",
    )
    capture_id = _insert_capture(datetime(2026, 5, 20, 10, 0), "Issue resolved")
    _link_capture(bucket_id, capture_id)

    sections = list_poi_sections_for_period(period)

    assert len(sections) == 1
    assert sections[0].status_change is not None
    assert "archived" in sections[0].status_change



def test_list_uncategorized_captures_excludes_categorized(rin_db: Path) -> None:
    period = _period()
    bucket_id = _insert_bucket("MyTopic", opened_at=datetime(2026, 5, 1, 9, 0))
    first = _insert_capture(datetime(2026, 5, 20, 9, 0), "Capture one")
    second = _insert_capture(datetime(2026, 5, 20, 10, 0), "Capture two")
    third = _insert_capture(datetime(2026, 5, 20, 11, 0), "Capture three")

    _link_capture(bucket_id, first)
    _link_capture(bucket_id, second)

    uncategorized = list_uncategorized_captures_for_period(period)

    assert [cap.id for cap in uncategorized] == [third]



def test_resolve_layout_auto_picks_per_poi_when_sections_present() -> None:
    cfg = RinConfig()
    cfg.reports.layout = "auto"

    assert _resolve_layout(cfg, [_sample_section()]) == "per_poi"
    assert _resolve_layout(cfg, []) == "chronological"



def test_resolve_layout_explicit_choice_wins() -> None:
    cfg = RinConfig()
    cfg.reports.layout = "chronological"

    assert _resolve_layout(cfg, [_sample_section()]) == "chronological"



def test_per_poi_jinja_template_renders_with_one_section_and_uncategorized() -> None:
    rendered = Template(POI_GROUPED_REPORT_TEMPLATE).render(
        kind="daily",
        period_start=_period().start,
        period_end=_period().end,
        items=[_sample_capture_item(1), _sample_capture_item(2, "Quick lookup")],
        poi_sections=[_sample_section()],
        uncategorized=[_sample_capture_item(2, "Quick lookup")],
    )

    assert "## MyTopic" in rendered
    assert "## Uncategorized" in rendered



def test_per_poi_jinja_template_renders_with_zero_sections_and_some_uncategorized() -> None:
    rendered = Template(POI_GROUPED_REPORT_TEMPLATE).render(
        kind="daily",
        period_start=_period().start,
        period_end=_period().end,
        items=[_sample_capture_item(2, "Quick lookup")],
        poi_sections=[],
        uncategorized=[_sample_capture_item(2, "Quick lookup")],
    )

    assert "_All captures were categorized into a topic._" not in rendered
    assert "## Uncategorized" in rendered



def test_generator_uses_per_poi_layout_end_to_end(rin_db: Path) -> None:
    period = _period()
    bucket_id = _insert_bucket("MyTopic", opened_at=datetime(2026, 5, 1, 9, 0))
    first = _insert_capture(datetime(2026, 5, 20, 9, 0), "Meeting about API redesign")
    second = _insert_capture(datetime(2026, 5, 20, 14, 30), "Deferred auth follow-up")
    third = _insert_capture(datetime(2026, 5, 20, 16, 0), "Quick Stack Overflow lookup")

    _link_capture(bucket_id, first)
    _link_capture(bucket_id, second)

    cfg = RinConfig()
    cfg.llm.name = "none"
    cfg.reports.layout = "per_poi"

    result = generate_report(period, cfg, out_dir=rin_db / "reports")
    body = result.path.read_text(encoding="utf-8")

    assert "## MyTopic" in body
    assert f"`cap-{first}`" in body
    assert f"`cap-{second}`" in body
    assert "## Uncategorized" in body
    assert f"`cap-{third}`" in body

"""Phase 1-D (v0.13.0): active-POI decay + noise filter.

Active-POI decay
- Both window and top_k come from ``cfg.skills.active_window_days`` /
  ``active_top_k`` (with the v0.10.0 defaults preserved).
- Window of 0 days returns nothing; that lets users opt out without
  removing the toggle.

Noise filter
- Off by default (zero behavioral change).
- When on, uncategorized captures whose summary is below
  ``cfg.reports.noise_min_ocr_chars`` collapse into a footer line.
- Captures are NEVER deleted; they remain in the DB and remain
  searchable in RAG.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.analysis.summarizer import _recent_topic_pois
from rin.config import RinConfig
from rin.reports.generator import (
    CaptureItem,
    PoIReportSection,
    ReportPeriod,
    _render_poi_grouped_offline,
    generate_report,
    partition_uncategorized_noise,
)
from rin.storage import db, init_db, session
from rin.storage.models import (
    Analysis,
    Bucket,
    Capture,
    CaptureBucket,
)


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


# ---------------------------------------------------------------------------
# Active-POI decay
# ---------------------------------------------------------------------------


def _seed_topic_capture(when: datetime, topic: str) -> int:
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", started_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary="text"))
        bucket = s.scalars(
            Bucket.__table__.select().where(
                Bucket.skill_name == "topic", Bucket.key == topic
            )
        ).first()
        if bucket is None:
            b = Bucket(skill_name="topic", key=topic, title=topic, opened_at=when)
            s.add(b)
            s.flush()
            bucket_id = b.id
        else:
            bucket_id = bucket.id
        s.add(CaptureBucket(capture_id=cap.id, bucket_id=bucket_id, created_at=when))
        s.flush()
        return cap.id


def test_recent_topic_pois_respects_window(rin_db: Path) -> None:
    """Window of 5 days excludes a topic touched 30 days ago."""

    _seed_topic_capture(datetime.now() - timedelta(days=30), "Old")
    _seed_topic_capture(datetime.now() - timedelta(days=1), "Fresh")
    names = _recent_topic_pois(limit=10, window_days=5)
    assert names == ["Fresh"]


def test_recent_topic_pois_respects_top_k(rin_db: Path) -> None:
    """Top-K=2 keeps only the two most-recently touched topics."""

    base = datetime.now()
    _seed_topic_capture(base - timedelta(hours=10), "Oldest")
    _seed_topic_capture(base - timedelta(hours=5), "Middle")
    _seed_topic_capture(base - timedelta(hours=1), "Newest")
    names = _recent_topic_pois(limit=2, window_days=30)
    assert names == ["Newest", "Middle"]


def test_recent_topic_pois_window_zero_returns_empty(rin_db: Path) -> None:
    """Window of 0 disables the fallback entirely."""

    _seed_topic_capture(datetime.now() - timedelta(hours=1), "Fresh")
    assert _recent_topic_pois(limit=10, window_days=0) == []


def test_recent_topic_pois_limit_zero_returns_empty(rin_db: Path) -> None:
    _seed_topic_capture(datetime.now() - timedelta(hours=1), "Fresh")
    assert _recent_topic_pois(limit=0, window_days=30) == []


def test_skills_config_defaults_match_phase_1a_constants() -> None:
    """Defaults must not silently shrink the v0.10.0 prompt window."""

    cfg = RinConfig()
    assert cfg.skills.active_window_days == 30
    assert cfg.skills.active_top_k == 5


# ---------------------------------------------------------------------------
# Noise filter
# ---------------------------------------------------------------------------


def _item(cap_id: int, summary: str) -> CaptureItem:
    return CaptureItem(
        id=cap_id,
        kind="screenshot",
        started_at=datetime(2026, 6, 1, 9, 0),
        duration_ms=None,
        monitor_count=1,
        summary=summary,
    )


def test_partition_noise_off_returns_all_kept() -> None:
    items = [_item(1, "x"), _item(2, "y" * 500)]
    kept, noise = partition_uncategorized_noise(
        items, skip_noise=False, min_chars=100
    )
    assert len(kept) == 2
    assert noise == []


def test_partition_noise_separates_short_captures() -> None:
    items = [
        _item(1, "x" * 20),  # noise
        _item(2, "y" * 200),  # kept
        _item(3, "z" * 50),  # noise
    ]
    kept, noise = partition_uncategorized_noise(
        items, skip_noise=True, min_chars=100
    )
    assert [i.id for i in kept] == [2]
    assert [i.id for i in noise] == [1, 3]


def test_partition_noise_threshold_zero_disables() -> None:
    items = [_item(1, ""), _item(2, "x" * 5)]
    kept, noise = partition_uncategorized_noise(
        items, skip_noise=True, min_chars=0
    )
    assert len(kept) == 2 and noise == []


def test_partition_noise_treats_none_summary_as_zero() -> None:
    item = CaptureItem(
        id=1,
        kind="screenshot",
        started_at=datetime.now(),
        duration_ms=None,
        monitor_count=1,
        summary=None,
    )
    kept, noise = partition_uncategorized_noise(
        [item], skip_noise=True, min_chars=10
    )
    assert kept == []
    assert noise == [item]


def test_offline_renderer_appends_noise_footer() -> None:
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 1, 0, 0),
        end=datetime(2026, 6, 2, 0, 0),
    )
    section = PoIReportSection(
        bucket_id=1,
        title="Atlas",
        status_change=None,
        captures=[_item(10, "Atlas long summary " * 20)],
        archive_path=None,
    )
    body = _render_poi_grouped_offline(
        period,
        items=section.captures,
        poi_sections=[section],
        uncategorized=[],
        noise_count=7,
    )
    assert "Light browsing: 7 low-signal capture(s)" in body


def test_offline_renderer_omits_noise_footer_when_zero() -> None:
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 1, 0, 0),
        end=datetime(2026, 6, 2, 0, 0),
    )
    section = PoIReportSection(
        bucket_id=1,
        title="Atlas",
        status_change=None,
        captures=[_item(10, "Atlas long summary " * 20)],
        archive_path=None,
    )
    body = _render_poi_grouped_offline(
        period,
        items=section.captures,
        poi_sections=[section],
        uncategorized=[],
        noise_count=0,
    )
    assert "Light browsing" not in body


# ---------------------------------------------------------------------------
# End-to-end: noise filter changes the report body
# ---------------------------------------------------------------------------


def _insert_capture(
    when: datetime, summary: str, *, bucket_id: int | None = None
) -> int:
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", started_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=summary))
        if bucket_id is not None:
            s.add(CaptureBucket(capture_id=cap.id, bucket_id=bucket_id))
        s.flush()
        return cap.id


def test_generate_report_with_skip_noise_collapses_uncategorized(
    rin_db: Path, tmp_path: Path
) -> None:
    # 1 categorized capture under Atlas + 1 long uncategorized (kept) +
    # 2 short uncategorized (noise).
    with session() as s:
        bucket = Bucket(
            skill_name="topic",
            key="Atlas",
            title="Atlas",
            opened_at=datetime(2026, 6, 1, 8, 0),
        )
        s.add(bucket)
        s.flush()
        bucket_id = bucket.id
    _insert_capture(
        datetime(2026, 6, 1, 9, 0), "Atlas activity " * 20, bucket_id=bucket_id
    )
    _insert_capture(datetime(2026, 6, 1, 10, 0), "x" * 30)  # noise
    _insert_capture(datetime(2026, 6, 1, 11, 0), "y" * 30)  # noise
    _insert_capture(
        datetime(2026, 6, 1, 12, 0),
        "Long uncategorized capture about reading docs and articles "
        "throughout the morning across multiple tabs",
    )  # kept

    cfg = RinConfig.model_validate(
        {"reports": {"layout": "per_poi", "skip_noise": True, "noise_min_ocr_chars": 80}}
    )
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 1, 0, 0),
        end=datetime(2026, 6, 2, 0, 0),
    )
    report = generate_report(period, cfg, provider=None, out_dir=tmp_path)
    body = report.body
    assert "Light browsing: 2 low-signal" in body
    assert "Atlas" in body


def test_generate_report_skip_noise_default_off_keeps_legacy_behavior(
    rin_db: Path, tmp_path: Path
) -> None:
    """Without the toggle, short uncategorized captures still render."""

    with session() as s:
        bucket = Bucket(
            skill_name="topic",
            key="Atlas",
            title="Atlas",
            opened_at=datetime(2026, 6, 1, 8, 0),
        )
        s.add(bucket)
        s.flush()
        bucket_id = bucket.id
    _insert_capture(
        datetime(2026, 6, 1, 9, 0), "Atlas activity " * 20, bucket_id=bucket_id
    )
    cap_short = _insert_capture(datetime(2026, 6, 1, 10, 0), "x" * 5)

    cfg = RinConfig.model_validate({"reports": {"layout": "per_poi"}})
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 1, 0, 0),
        end=datetime(2026, 6, 2, 0, 0),
    )
    report = generate_report(period, cfg, provider=None, out_dir=tmp_path)
    body = report.body
    assert "Light browsing" not in body
    assert f"cap-{cap_short}" in body

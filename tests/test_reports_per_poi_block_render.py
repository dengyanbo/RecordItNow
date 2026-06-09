"""Phase 1-B: report renderer uses per-POI block when present."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.reports.generator import (
    ReportPeriod,
    generate_report,
    list_poi_sections_for_period,
)
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Bucket, Capture, CaptureBucket, CaptureFile


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _seed_capture_with_blocks(
    started_at: datetime,
    *,
    general: str,
    poi_blocks: list[tuple[str, str]],
) -> int:
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="analyzed",
            folder="/tmp",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=1),
        )
        cap.files = [
            CaptureFile(
                monitor_index=1,
                path="/tmp/m1.png",
                media_type="image/png",
                width=10,
                height=10,
            )
        ]
        s.add(cap)
        s.flush()
        cap_id = cap.id
        s.add(
            Analysis(
                capture_id=cap_id,
                summary=general,
                analysis_json=json.dumps(
                    {
                        "schema_version": 1,
                        "general_summary": general,
                        "poi_blocks": [{"poi": p, "block": b} for p, b in poi_blocks],
                    }
                ),
            )
        )
        for poi, _ in poi_blocks:
            b = s.scalars(
                __import__("sqlalchemy").select(Bucket).where(
                    Bucket.skill_name == "topic", Bucket.key == poi
                )
            ).first()
            if b is None:
                b = Bucket(skill_name="topic", key=poi, title=poi)
                s.add(b)
                s.flush()
            s.add(CaptureBucket(capture_id=cap_id, bucket_id=b.id))
        return cap_id


def test_section_uses_poi_block_instead_of_general_summary(rin_db: Path) -> None:
    started = datetime(2026, 6, 8, 10, 0, 0)
    _seed_capture_with_blocks(
        started,
        general="General paragraph about everything.",
        poi_blocks=[
            ("Atlas", "Atlas-specific narrative."),
            ("Beacon", "Beacon-specific narrative."),
        ],
    )

    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 8, 0, 0, 0),
        end=datetime(2026, 6, 9, 0, 0, 0),
    )
    sections = list_poi_sections_for_period(period)

    titles = {sec.title for sec in sections}
    assert titles == {"Atlas", "Beacon"}

    atlas_section = next(s for s in sections if s.title == "Atlas")
    assert atlas_section.captures[0].summary == "Atlas-specific narrative."

    beacon_section = next(s for s in sections if s.title == "Beacon")
    assert beacon_section.captures[0].summary == "Beacon-specific narrative."


def test_section_falls_back_to_general_when_block_missing(rin_db: Path) -> None:
    started = datetime(2026, 6, 8, 10, 0, 0)
    # Bucket exists for Atlas but the analysis_json has NO block for it.
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="analyzed",
            folder="/tmp",
            started_at=started,
            ended_at=started + timedelta(seconds=1),
        )
        cap.files = [
            CaptureFile(
                monitor_index=1,
                path="/tmp/m1.png",
                media_type="image/png",
                width=10,
                height=10,
            )
        ]
        s.add(cap)
        s.flush()
        cap_id = cap.id
        s.add(
            Analysis(
                capture_id=cap_id,
                summary="general paragraph",
                analysis_json=json.dumps(
                    {"schema_version": 1, "general_summary": "general paragraph",
                     "poi_blocks": []}
                ),
            )
        )
        b = Bucket(skill_name="topic", key="Atlas", title="Atlas")
        s.add(b)
        s.flush()
        s.add(CaptureBucket(capture_id=cap_id, bucket_id=b.id))

    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 8, 0, 0, 0),
        end=datetime(2026, 6, 9, 0, 0, 0),
    )
    sections = list_poi_sections_for_period(period)
    assert sections[0].captures[0].summary == "general paragraph"


def test_generated_report_includes_poi_block_text(rin_db: Path) -> None:
    """End-to-end: the rendered markdown shows the per-POI block text
    under the relevant section header (per_poi layout, no provider →
    offline Jinja template)."""

    started = datetime(2026, 6, 8, 10, 0, 0)
    _seed_capture_with_blocks(
        started,
        general="general paragraph that should NOT appear in atlas section",
        poi_blocks=[("Atlas", "ATLAS_NARRATIVE_MARKER")],
    )

    cfg = RinConfig.model_validate({"reports": {"layout": "per_poi"}})
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 8, 0, 0, 0),
        end=datetime(2026, 6, 9, 0, 0, 0),
    )
    rep = generate_report(period, cfg, out_dir=rin_db / "out")

    body = rep.body
    # The Atlas section uses the block, not the general summary.
    assert "ATLAS_NARRATIVE_MARKER" in body
    # The general summary doesn't leak into the Atlas section.
    assert "general paragraph that should NOT" not in body

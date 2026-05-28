"""End-to-end test for the skill pipeline using real SQLite.

The 5-capture fixture from plan.md:
- 4 captures mention INC0012345 across a journey
- 1 capture mentions only PROJ-42 (unrelated to support_ticket skill)
- The final cap-5 contains "Status: Closed"

We then run the BucketScheduler tick and assert that the bucket has
been archived to ``reports/archives/support_ticket/INC0012345.md``
and that the archive references every cap-N that contributed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.skills.pipeline import classify_capture
from rin.skills.scheduler import BucketScheduler
from rin.storage import (
    Bucket,
    Capture,
    CaptureBucket,
    db,
    init_db,
    session,
)


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Spin up a fresh SQLite DB in a tmp directory and tear it down."""

    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _insert_capture(
    when: datetime,
    summary: str,
    *,
    ocr: str = "",
    kind: str = "screenshot",
) -> int:
    """Insert a Capture + matching Analysis row. Returns capture id."""

    from rin.storage.models import Analysis

    with session() as s:
        cap = Capture(kind=kind, status="analyzed", started_at=when)
        s.add(cap)
        s.flush()
        a = Analysis(
            capture_id=cap.id,
            summary=summary,
            ocr_text=ocr or None,
        )
        s.add(a)
        s.flush()
        return cap.id


def _ticket_fixture(now: datetime) -> list[int]:
    """The 5-capture fixture. Returns the inserted capture ids in order."""

    return [
        _insert_capture(
            now - timedelta(days=3, hours=2),
            "Opened email about INC0012345 — login fails for user X at ACME",
            ocr="Subject: INC0012345 - Login failure\nFrom: customer@acme.com",
        ),
        _insert_capture(
            now - timedelta(days=2, hours=4),
            "Investigating INC0012345 — checked AD account, user is locked out",
        ),
        # Unrelated capture
        _insert_capture(
            now - timedelta(days=2, hours=1),
            "Unrelated work on JIRA card PROJ-42 (refactor login service)",
        ),
        _insert_capture(
            now - timedelta(days=1),
            "INC0012345 — unlocked account in AD, asked customer to retry",
        ),
        _insert_capture(
            now,
            "INC0012345 — customer confirms working. Status: Closed",
        ),
    ]


def _enable_support_ticket(cfg: RinConfig) -> None:
    cfg.skills.enabled = ["support_ticket"]


def test_classification_links_only_matching_captures(rin_db) -> None:
    cfg = RinConfig()
    _enable_support_ticket(cfg)
    now = datetime.now()
    cap_ids = _ticket_fixture(now)

    for cid in cap_ids:
        with session() as s:
            cap = s.get(Capture, cid)
            analysis = cap.analyses[-1]
            summary = analysis.summary
            ocr = analysis.ocr_text or ""
        classify_capture(cid, cfg, summary=summary, ocr_text=ocr)

    with session() as s:
        buckets = s.scalars(select(Bucket)).all()
        # Exactly one bucket for INC0012345.
        keys = sorted(b.key for b in buckets)
        assert keys == ["INC0012345"]

        bucket = buckets[0]
        links = s.scalars(
            select(CaptureBucket).where(CaptureBucket.bucket_id == bucket.id)
        ).all()
        linked = sorted(link.capture_id for link in links)
        # All except the unrelated PROJ-42 capture (cap_ids[2]) should be linked.
        expected = sorted([cap_ids[0], cap_ids[1], cap_ids[3], cap_ids[4]])
        assert linked == expected


def test_scheduler_archives_bucket_when_closed_phrase_present(rin_db) -> None:
    cfg = RinConfig()
    _enable_support_ticket(cfg)
    cfg.skills.closure_check_hours = 1  # Configured but we'll force-tick.
    now = datetime.now()
    cap_ids = _ticket_fixture(now)

    for cid in cap_ids:
        with session() as s:
            cap = s.get(Capture, cid)
            analysis = cap.analyses[-1]
            summary = analysis.summary
            ocr = analysis.ocr_text or ""
        classify_capture(cid, cfg, summary=summary, ocr_text=ocr)

    sched = BucketScheduler(cfg)
    # No start() — we want a single deterministic tick.
    archived_count = sched.tick(force=True)
    assert archived_count == 1

    with session() as s:
        bucket = s.scalars(
            select(Bucket).where(Bucket.key == "INC0012345")
        ).one()
        assert bucket.status == "archived"
        assert bucket.closed_at is not None
        assert bucket.archive_path is not None
        archive_path = Path(bucket.archive_path)

    assert archive_path.exists()
    md = archive_path.read_text(encoding="utf-8")
    # Every contributing capture must be referenced.
    for cid in (cap_ids[0], cap_ids[1], cap_ids[3], cap_ids[4]):
        assert f"cap-{cid}" in md, f"missing cap-{cid} in archive:\n{md}"
    # The unrelated capture must NOT appear.
    assert f"cap-{cap_ids[2]}" not in md
    # The archive lives under reports/archives/support_ticket/
    assert archive_path.parent.name == "support_ticket"
    assert archive_path.parent.parent.name == "archives"


def test_scheduler_does_nothing_when_no_skills_enabled(rin_db) -> None:
    cfg = RinConfig()
    # skills.enabled is empty by default.
    _ticket_fixture(datetime.now())

    sched = BucketScheduler(cfg)
    assert sched.tick(force=True) == 0
    with session() as s:
        assert s.scalars(select(Bucket)).all() == []


def test_reclassifying_same_capture_does_not_duplicate_bucket(rin_db) -> None:
    cfg = RinConfig()
    _enable_support_ticket(cfg)
    now = datetime.now()
    cap_id = _insert_capture(now, "INC0012345 — first pass")

    classify_capture(cap_id, cfg, summary="INC0012345 — first pass", ocr_text="")
    # Same key, different prose — should not create a second bucket.
    classify_capture(
        cap_id, cfg, summary="INC0012345 — second pass with more context", ocr_text=""
    )

    with session() as s:
        buckets = s.scalars(select(Bucket)).all()
        assert len(buckets) == 1
        links = s.scalars(
            select(CaptureBucket).where(CaptureBucket.bucket_id == buckets[0].id)
        ).all()
        # Junction insert is idempotent — single link row.
        assert len(links) == 1

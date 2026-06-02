from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.skills.pipeline import classify_capture
from rin.storage import Bucket, db, init_db, session
from rin.storage.models import Analysis, Capture, Transcript
from rin.utils.logging import get_logger

log = get_logger(__name__)


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


def _topic_cfg() -> RinConfig:
    return RinConfig.model_validate(
        {
            "skills": {
                "enabled": ["topic"],
                "topic": {
                    "topics": [
                        {
                            "name": "Project Atlas",
                            "keywords": ["atlas"],
                        }
                    ]
                },
            }
        }
    )


def _insert_video_capture(
    *,
    transcript: str,
    summary: str = "brief",
    ocr_text: str = "",
) -> int:
    now = datetime(2026, 5, 21, 14, 0, 0)
    with session() as s:
        cap = Capture(
            kind="video",
            status="analyzed",
            started_at=now,
            ended_at=now,
        )
        s.add(cap)
        s.flush()
        s.add(
            Analysis(
                capture_id=cap.id,
                summary=summary,
                ocr_text=ocr_text or None,
            )
        )
        s.add(Transcript(capture_id=cap.id, text=transcript))
        s.flush()
        return cap.id


def _topic_bucket_keys() -> list[str]:
    with session() as s:
        return list(
            s.scalars(
                select(Bucket.key).where(Bucket.skill_name == "topic").order_by(Bucket.key.asc())
            )
        )


def test_classify_capture_creates_topic_bucket_from_transcript(rin_db: Path) -> None:
    transcript = "Project Atlas team kicked off the sprint planning today."
    cap_id = _insert_video_capture(transcript=transcript)

    bucket_ids = classify_capture(
        cap_id,
        _topic_cfg(),
        summary="brief",
        ocr_text="",
        transcript=transcript,
    )

    assert len(bucket_ids) == 1
    assert _topic_bucket_keys() == ["Project Atlas"]


def test_classify_capture_matches_long_transcript_past_prompt_truncation(rin_db: Path) -> None:
    transcript = (
        ("x" * 2500)
        + " Project Atlas team kicked off the sprint planning today. "
        + ("y" * 450)
    )
    cap_id = _insert_video_capture(transcript=transcript)

    bucket_ids = classify_capture(
        cap_id,
        _topic_cfg(),
        summary="brief",
        ocr_text="",
        transcript=transcript,
    )

    assert len(transcript) >= 3000
    assert len(bucket_ids) == 1
    assert _topic_bucket_keys() == ["Project Atlas"]


def test_classify_capture_transcript_only_match_without_ocr_keyword(rin_db: Path) -> None:
    transcript = "Weekly check-in for Project Atlas shipped more backlog cleanup."
    cap_id = _insert_video_capture(
        transcript=transcript,
        summary="brief",
        ocr_text="Dashboard for unrelated quarterly metrics",
    )

    bucket_ids = classify_capture(
        cap_id,
        _topic_cfg(),
        summary="brief",
        ocr_text="Dashboard for unrelated quarterly metrics",
        transcript=transcript,
    )

    assert len(bucket_ids) == 1
    assert _topic_bucket_keys() == ["Project Atlas"]


def test_classify_capture_ignores_unrelated_transcript(rin_db: Path) -> None:
    transcript = "Project Phoenix team kicked off the sprint planning today."
    cap_id = _insert_video_capture(transcript=transcript)

    bucket_ids = classify_capture(
        cap_id,
        _topic_cfg(),
        summary="brief",
        ocr_text="",
        transcript=transcript,
    )

    assert bucket_ids == []
    assert _topic_bucket_keys() == []

"""Phase 1-A guarantee: classify_capture runs BEFORE build_summary.

Today's pre-Phase-A bug was the opposite — build_summary was called with
every configured POI name, then classify ran afterwards. With the order
flipped, the prompt's "tracked topics" line lists only POIs actually
detected in this capture (or recent ones as fallback).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import rin.analysis.summarizer as summarizer_module
from rin import paths as paths_mod
from rin.analysis.summarizer import analyze_capture
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis
from rin.storage import db, init_db, session
from rin.storage.models import Bucket, Capture, CaptureBucket, CaptureFile


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _insert_screenshot(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    image_path = root / "monitor-1.png"
    image_path.write_bytes(b"\x89PNG")
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="captured",
            folder=str(root),
            started_at=datetime(2026, 5, 21, 14, 0, 0),
            ended_at=datetime(2026, 5, 21, 14, 0, 1),
        )
        cap.files = [
            CaptureFile(
                monitor_index=1,
                path=str(image_path),
                media_type="image/png",
                width=100,
                height=100,
            )
        ]
        s.add(cap)
        s.flush()
        return cap.id


def test_classify_runs_before_build_summary(
    rin_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap_id = _insert_screenshot(rin_db / "capture")
    cfg = RinConfig.model_validate({"skills": {"enabled": ["topic"]}})
    call_order: list[str] = []

    def fake_classify(capture_id, _cfg, **kwargs):  # noqa: ARG001
        call_order.append("classify")
        with session() as s:
            b = Bucket(skill_name="topic", key="Atlas", title="Atlas")
            s.add(b)
            s.flush()
            s.add(CaptureBucket(capture_id=capture_id, bucket_id=b.id))
            return [b.id]

    def fake_build_summary(capture, **kwargs):  # noqa: ARG001
        call_order.append("summary")
        # The summary builder should see the detected POI, not all of config.
        assert kwargs["active_pois"] == ["Atlas"]
        return "summary text"

    monkeypatch.setattr("rin.skills.pipeline.classify_capture", fake_classify)
    monkeypatch.setattr(summarizer_module, "build_summary", fake_build_summary)

    analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="hi", text="ocr"),
    )

    assert call_order == ["classify", "summary"]


def test_classify_receives_empty_summary_phase_1a(
    rin_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skills now run before the summary exists; the contract is that
    they detect from OCR + transcript and ignore an empty ``summary``."""

    cap_id = _insert_screenshot(rin_db / "capture")
    cfg = RinConfig.model_validate({"skills": {"enabled": ["topic"]}})
    seen: dict[str, object] = {}

    def fake_classify(capture_id, _cfg, **kwargs):  # noqa: ARG001
        seen.update(kwargs)
        return []

    monkeypatch.setattr("rin.skills.pipeline.classify_capture", fake_classify)
    monkeypatch.setattr(summarizer_module, "build_summary", lambda c, **k: "ok")

    analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="hi", text="some ocr"),
    )

    assert seen["summary"] == ""
    assert "some ocr" in (seen.get("ocr_text") or "")

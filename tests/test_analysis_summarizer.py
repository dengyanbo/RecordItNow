"""End-to-end summarizer tests with mocked analyzers + provider."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin.analysis.summarizer import analyze_capture, analyze_pending, build_summary
from rin.analysis.transcribe import Transcript
from rin.analysis.video_analyzer import VideoAnalysis
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Capture, CaptureFile
from rin.storage.models import Transcript as TranscriptModel


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


class _FakeProvider(Provider):
    name = "fake"
    model = "fake-1"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=True, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="img-sum", text="img-text")

    def analyze_text(self, prompt, *, system=None):
        return "FINAL SUMMARY"

    def chat(self, messages):
        return "chat"


def _make_screenshot_capture(tmp_path: Path) -> int:
    tmp_path.mkdir(parents=True, exist_ok=True)
    img = tmp_path / "monitor-1.png"
    img.write_bytes(b"\x89PNG")
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="captured",
            folder=str(tmp_path),
            started_at=datetime(2026, 5, 21, 14, 0, 0),
            ended_at=datetime(2026, 5, 21, 14, 0, 1),
        )
        cap.files = [
            CaptureFile(monitor_index=1, path=str(img), media_type="image/png", width=100, height=100)
        ]
        s.add(cap)
        s.flush()
        return cap.id


def _make_video_capture(tmp_path: Path) -> int:
    vid = tmp_path / "monitor-1.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypisom")
    with session() as s:
        cap = Capture(
            kind="video",
            status="captured",
            folder=str(tmp_path),
            started_at=datetime(2026, 5, 21, 14, 0, 0),
            ended_at=datetime(2026, 5, 21, 14, 0, 30),
        )
        cap.files = [CaptureFile(monitor_index=1, path=str(vid), media_type="video/mp4")]
        s.add(cap)
        s.flush()
        return cap.id


def test_build_summary_uses_provider_when_available() -> None:
    cap = Capture(kind="screenshot")
    summary = build_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="x"), ImageAnalysis(summary="y")],
        provider=_FakeProvider(),
    )
    assert summary == "FINAL SUMMARY"


def test_build_summary_fallback_when_no_provider() -> None:
    cap = Capture(kind="screenshot")
    summary = build_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="A meeting in Teams")],
    )
    assert summary.startswith("Screenshot captured")
    assert "meeting" in summary.lower()


def test_build_summary_empty_when_no_data() -> None:
    cap = Capture(kind="video")
    assert "no extractable text" in build_summary(cap).lower()


def test_analyze_capture_writes_analysis_and_updates_status(tmp_path: Path) -> None:
    cap_id = _make_screenshot_capture(tmp_path)
    aid = analyze_capture(
        cap_id,
        RinConfig(),
        provider=_FakeProvider(),
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="hello", text="text"),
    )
    assert isinstance(aid, int)
    with session() as s:
        cap = s.get(Capture, cap_id)
        assert cap.status == "analyzed"
        an = s.get(Analysis, aid)
        assert an.summary == "FINAL SUMMARY"
        assert "text" in (an.ocr_text or "")
        assert an.llm_provider == "fake"
        assert an.llm_model == "fake-1"


def test_analyze_capture_video_writes_transcript(tmp_path: Path) -> None:
    cap_id = _make_video_capture(tmp_path)

    def fake_video(path, *, cfg, provider=None, **kwargs):
        return VideoAnalysis(
            frame_summaries=["frame summary"],
            ocr_text="frame ocr",
            transcript=Transcript(text="hello world", language="en", segments=[{"start": 0, "end": 1, "text": "hello world"}]),
        )

    aid = analyze_capture(
        cap_id,
        RinConfig(),
        provider=_FakeProvider(),
        video_analyzer_fn=fake_video,
    )
    assert isinstance(aid, int)
    with session() as s:
        ts = s.scalars(
            __import__("sqlalchemy").select(TranscriptModel).where(TranscriptModel.capture_id == cap_id)
        ).all()
    assert len(ts) == 1
    assert ts[0].text == "hello world"
    assert ts[0].language == "en"


def test_analyze_pending_picks_unanalyzed(tmp_path: Path) -> None:
    cap_a = _make_screenshot_capture(tmp_path / "a")
    cap_b = _make_screenshot_capture(tmp_path / "b")
    # Mark a as already analyzed.
    with session() as s:
        s.get(Capture, cap_a).status = "analyzed"

    aids = analyze_pending(
        RinConfig(),
        provider=_FakeProvider(),
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="x", text="y"),
    )
    assert len(aids) == 1
    with session() as s:
        assert s.get(Capture, cap_b).status == "analyzed"


def test_analyze_capture_calls_embedder(tmp_path: Path) -> None:
    cap_id = _make_screenshot_capture(tmp_path)
    seen: list = []

    def embedder(text: str) -> list[float]:
        seen.append(text)
        return [0.1] * 8

    analyze_capture(
        cap_id,
        RinConfig(),
        provider=_FakeProvider(),
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="x", text="y"),
        embedder=embedder,
    )
    assert len(seen) == 1
    assert "FINAL SUMMARY" in seen[0]

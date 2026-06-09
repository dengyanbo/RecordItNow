"""Phase 1-B: ``build_structured_summary`` + ``analyze_capture`` persist JSON."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.analysis.structured import StructuredAnalysis
from rin.analysis.summarizer import analyze_capture, build_structured_summary
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, LLMError, Provider, ProviderCapabilities
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


class StubProvider(Provider):
    name = "stub"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis:
        raise NotImplementedError

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        self.systems.append(system)
        if not self.replies:
            raise LLMError("ran out of stub replies")
        return self.replies.pop(0)

    def chat(self, messages):
        raise NotImplementedError


def _insert_capture(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    p = root / "monitor-1.png"
    p.write_bytes(b"\x89PNG")
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="captured",
            folder=str(root),
            started_at=datetime(2026, 6, 9, 12, 0, 0),
            ended_at=datetime(2026, 6, 9, 12, 0, 1),
        )
        cap.files = [
            CaptureFile(
                monitor_index=1,
                path=str(p),
                media_type="image/png",
                width=10,
                height=10,
            )
        ]
        s.add(cap)
        s.flush()
        return cap.id


def test_build_structured_summary_no_provider_falls_back_to_plain() -> None:
    cap = Capture(kind="screenshot")
    out = build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="some work")],
        provider=None,
        detected_pois=["A"],
        max_poi_blocks=2,
    )
    assert isinstance(out, StructuredAnalysis)
    assert out.poi_blocks == ()
    assert "some work" in out.general_summary.lower()


def test_build_structured_summary_no_detected_pois_skips_json_ask() -> None:
    cap = Capture(kind="screenshot")
    provider = StubProvider("plain summary text")

    out = build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="x")],
        provider=provider,
        detected_pois=[],
        fallback_pois=["Recent"],
        max_poi_blocks=2,
    )

    assert out.general_summary == "plain summary text"
    assert out.poi_blocks == ()
    # The Phase 1-A "tracked topics" line was passed through to the
    # plain summary prompt using the fallback list.
    assert "Recent" in provider.prompts[0]


def test_build_structured_summary_with_pois_parses_json_response() -> None:
    cap = Capture(kind="screenshot")
    provider = StubProvider(
        json.dumps(
            {
                "schema_version": 1,
                "general_summary": "Worked on Atlas + Beacon",
                "poi_blocks": [
                    {"poi": "Atlas", "block": "fixed bug"},
                    {"poi": "Beacon", "block": "reviewed PR"},
                ],
            }
        )
    )

    out = build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="things")],
        provider=provider,
        detected_pois=["Atlas", "Beacon"],
        max_poi_blocks=2,
    )

    assert out.general_summary == "Worked on Atlas + Beacon"
    assert len(out.poi_blocks) == 2
    assert out.block_for("atlas") == "fixed bug"


def test_build_structured_summary_caps_at_max_blocks() -> None:
    cap = Capture(kind="screenshot")
    provider = StubProvider(
        json.dumps(
            {"general_summary": "g", "poi_blocks": [{"poi": "A", "block": "a"}]}
        )
    )

    build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="x")],
        provider=provider,
        detected_pois=["A", "B", "C"],
        max_poi_blocks=1,
    )

    # The prompt only mentions A — B and C are capped out.
    assert "- A" in provider.prompts[0]
    assert "- B" not in provider.prompts[0]


def test_build_structured_summary_max_blocks_zero_skips_json() -> None:
    cap = Capture(kind="screenshot")
    provider = StubProvider("plain text")

    out = build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="x")],
        provider=provider,
        detected_pois=["A"],
        max_poi_blocks=0,
    )

    assert out.poi_blocks == ()
    # Plain summary system prompt indicates JSON ask was skipped.
    assert provider.systems[0] == "You write concise, factual activity summaries."


def test_build_structured_summary_garbage_reply_uses_raw_as_general() -> None:
    cap = Capture(kind="screenshot")
    provider = StubProvider("definitely not JSON, just prose here.")

    out = build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="x")],
        provider=provider,
        detected_pois=["A"],
        max_poi_blocks=2,
    )

    assert out.general_summary == "definitely not JSON, just prose here."
    assert out.poi_blocks == ()


def test_build_structured_summary_provider_raises_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = Capture(kind="screenshot")
    # Provider raises on the structured ask but second call (plain fallback) works.
    provider = StubProvider()  # empty: first call will raise

    def alternating_analyze_text(prompt, *, system=None):
        if "Return ONLY a single JSON object" in prompt:
            raise LLMError("boom")
        return "fallback plain summary"

    monkeypatch.setattr(provider, "analyze_text", alternating_analyze_text)

    out = build_structured_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="x")],
        provider=provider,
        detected_pois=["A"],
        max_poi_blocks=2,
    )

    assert out.general_summary == "fallback plain summary"
    assert out.poi_blocks == ()


def test_analyze_capture_persists_analysis_json(
    rin_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: analyze_capture writes the structured payload into the
    new ``analyses.analysis_json`` column."""

    cap_id = _insert_capture(rin_db / "cap")
    cfg = RinConfig.model_validate({"skills": {"enabled": ["topic"]}})

    def fake_classify(capture_id, _cfg, **kwargs):  # noqa: ARG001
        with session() as s:
            b = Bucket(skill_name="topic", key="Atlas", title="Atlas")
            s.add(b)
            s.flush()
            s.add(CaptureBucket(capture_id=capture_id, bucket_id=b.id))
            return [b.id]

    monkeypatch.setattr("rin.skills.pipeline.classify_capture", fake_classify)

    provider = StubProvider(
        json.dumps(
            {
                "schema_version": 1,
                "general_summary": "Atlas work",
                "poi_blocks": [{"poi": "Atlas", "block": "Reviewed queue"}],
            }
        )
    )

    aid = analyze_capture(
        cap_id,
        cfg,
        provider=provider,
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="hi", text="ocr"),
    )

    assert isinstance(aid, int)
    with session() as s:
        row = s.get(Analysis, aid)
    assert row is not None
    assert row.summary == "Atlas work"
    parsed = json.loads(row.analysis_json or "{}")
    assert parsed["general_summary"] == "Atlas work"
    assert parsed["poi_blocks"][0]["poi"] == "Atlas"
    assert parsed["poi_blocks"][0]["block"] == "Reviewed queue"


def test_analyze_capture_no_provider_still_writes_analysis_json(
    rin_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a provider, ``analysis_json`` holds the general summary
    only (empty poi_blocks) so downstream consumers always have valid JSON."""

    cap_id = _insert_capture(rin_db / "cap")
    cfg = RinConfig.model_validate({"skills": {"enabled": []}})
    monkeypatch.setattr("rin.skills.pipeline.classify_capture", lambda *a, **k: [])

    aid = analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda p, provider=None: ImageAnalysis(summary="hi", text="ocr"),
    )

    with session() as s:
        row = s.get(Analysis, aid)
    parsed = json.loads(row.analysis_json or "{}")
    assert parsed["poi_blocks"] == []
    assert parsed["general_summary"]  # non-empty fallback paragraph

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import rin.analysis.summarizer as summarizer_module
from rin import paths as paths_mod
from rin.analysis.summarizer import (
    _active_topic_names,
    _recent_topic_pois,
    _topic_pois_from_buckets,
    analyze_capture,
    build_summary,
)
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.storage import db, init_db, session
from rin.storage.models import Bucket, Capture, CaptureBucket, CaptureFile
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


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.system_prompts: list[str | None] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis:
        raise NotImplementedError

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        self.system_prompts.append(system)
        return self.responses.pop(0)

    def chat(self, messages):
        raise NotImplementedError


def _topic_cfg(topics: list[dict] | None = None, *, enabled: bool = True) -> RinConfig:
    payload: dict[str, object] = {
        "skills": {
            "enabled": ["topic"] if enabled else [],
        }
    }
    if topics is not None:
        payload["skills"]["topic"] = {"topics": topics}
    return RinConfig.model_validate(payload)


def _insert_screenshot_capture(root: Path) -> int:
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


def test_build_summary_no_pois_unchanged_prompt() -> None:
    cap = Capture(kind="screenshot")
    provider = FakeProvider("FINAL SUMMARY")

    summary = build_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="Project board")],
        provider=provider,
        active_pois=None,
    )

    assert summary == "FINAL SUMMARY"
    assert "tracked topics" not in provider.prompts[0]


def test_build_summary_with_pois_prepends_context() -> None:
    cap = Capture(kind="screenshot")
    provider = FakeProvider("FINAL SUMMARY")

    build_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="Project board")],
        provider=provider,
        active_pois=["Project Atlas", "Customer Ops", "Sprint Planning"],
    )

    prompt = provider.prompts[0]
    assert prompt.startswith(
        "This capture touched the following tracked topics: Project Atlas, "
        "Customer Ops, Sprint Planning. Focus your summary on what happened "
        "with them.\n"
    )


def test_build_summary_with_pois_no_provider_no_crash() -> None:
    cap = Capture(kind="screenshot")

    summary = build_summary(
        cap,
        image_analyses=[ImageAnalysis(summary="Atlas task board")],
        active_pois=["Project Atlas"],
    )

    assert summary.startswith("Screenshot captured")
    assert "atlas task board" in summary.lower()


def test_active_topic_names_returns_empty_when_topic_skill_disabled() -> None:
    cfg = _topic_cfg([{"name": "Project Atlas"}], enabled=False)

    assert _active_topic_names(cfg) == []


def test_active_topic_names_returns_empty_when_topic_skill_enabled_but_no_topics() -> None:
    cfg = _topic_cfg(None, enabled=True)

    assert _active_topic_names(cfg) == []


def test_active_topic_names_returns_names() -> None:
    cfg = _topic_cfg([{"name": "Project Atlas"}, {"name": "Customer Ops"}])

    assert _active_topic_names(cfg) == ["Project Atlas", "Customer Ops"]


def test_active_topic_names_tolerates_malformed_topics() -> None:
    cfg = _topic_cfg([
        {"description": "missing name"},
        "Project Atlas",
        {"name": "  Valid Topic  "},
    ])

    assert _active_topic_names(cfg) == ["Valid Topic"]


def test_topic_pois_from_buckets_filters_by_skill_name(rin_db: Path) -> None:
    with session() as s:
        topic_bucket = Bucket(skill_name="topic", key="Atlas", title="Atlas")
        ticket_bucket = Bucket(skill_name="support_ticket", key="T-1", title="T-1")
        s.add_all([topic_bucket, ticket_bucket])
        s.flush()
        topic_id = topic_bucket.id
        ticket_id = ticket_bucket.id

    out = _topic_pois_from_buckets([ticket_id, topic_id])

    assert out == ["Atlas"]


def test_topic_pois_from_buckets_preserves_input_order_dedupes(rin_db: Path) -> None:
    with session() as s:
        b1 = Bucket(skill_name="topic", key="Atlas", title="Atlas")
        b2 = Bucket(skill_name="topic", key="Beacon", title="Beacon")
        s.add_all([b1, b2])
        s.flush()
        ids = [b2.id, b1.id, b2.id]

    assert _topic_pois_from_buckets(ids) == ["Beacon", "Atlas"]


def test_topic_pois_from_buckets_empty_returns_empty() -> None:
    assert _topic_pois_from_buckets([]) == []


def test_recent_topic_pois_returns_topk_most_recent(rin_db: Path) -> None:
    from datetime import timedelta

    cap_id = _insert_screenshot_capture(rin_db / "capture")
    now = datetime.now()
    with session() as s:
        # Insert with explicit ascending created_at so ordering is deterministic
        # (sqlite's func.now() has only second resolution; same-millisecond
        # inserts won't sort correctly). Use offsets relative to "now" so the
        # 14-day fallback window always covers these rows.
        for offset, name in enumerate(["Older", "Middle", "Newer", "Newest"]):
            b = Bucket(skill_name="topic", key=name, title=name)
            s.add(b)
            s.flush()
            s.add(
                CaptureBucket(
                    capture_id=cap_id,
                    bucket_id=b.id,
                    created_at=now - timedelta(hours=10 - offset),
                )
            )

    out = _recent_topic_pois(limit=3)

    assert out == ["Newest", "Newer", "Middle"]


def test_recent_topic_pois_excludes_non_topic_skills(rin_db: Path) -> None:
    cap_id = _insert_screenshot_capture(rin_db / "capture")
    with session() as s:
        topic = Bucket(skill_name="topic", key="Atlas", title="Atlas")
        other = Bucket(skill_name="support_ticket", key="T-1", title="T-1")
        s.add_all([topic, other])
        s.flush()
        s.add_all([
            CaptureBucket(capture_id=cap_id, bucket_id=topic.id),
            CaptureBucket(capture_id=cap_id, bucket_id=other.id),
        ])

    assert _recent_topic_pois(limit=5) == ["Atlas"]


def test_recent_topic_pois_empty_when_nothing_tracked(rin_db: Path) -> None:
    assert _recent_topic_pois(limit=5) == []


def test_analyze_capture_uses_detected_pois_not_configured(
    rin_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 1-A contract: ``active_pois`` passed to ``build_summary`` reflects
    *detected* topic buckets (returned by classify_capture), not the full list
    of configured names. Today's bug was that 30 configured POIs would flood
    every prompt regardless of relevance.
    """

    cap_id = _insert_screenshot_capture(rin_db / "capture")
    cfg = _topic_cfg([
        {"name": "MyTopic", "keywords": ["topic"]},
        {"name": "Unrelated", "keywords": ["nope"]},
        {"name": "AnotherMiss", "keywords": ["xyz"]},
    ])
    seen: dict[str, object] = {}

    def fake_classify(capture_id, _cfg, **kwargs):  # noqa: ARG001
        with session() as s:
            b = Bucket(skill_name="topic", key="MyTopic", title="MyTopic")
            s.add(b)
            s.flush()
            s.add(CaptureBucket(capture_id=capture_id, bucket_id=b.id))
            return [b.id]

    def fake_build_summary(capture: Capture, **kwargs) -> str:
        seen["capture_id"] = capture.id
        seen.update(kwargs)
        return "brief"

    monkeypatch.setattr(summarizer_module, "build_summary", fake_build_summary)
    monkeypatch.setattr("rin.skills.pipeline.classify_capture", fake_classify)

    aid = analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda path, provider=None: ImageAnalysis(summary="hello", text="ocr"),
    )

    assert isinstance(aid, int)
    assert seen["capture_id"] == cap_id
    # Only the detected POI ends up in the prompt — NOT the 2 unrelated ones.
    assert seen["active_pois"] == ["MyTopic"]


def test_analyze_capture_falls_back_to_recent_pois_when_no_match(
    rin_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When classify returns no buckets for *this* capture, the summarizer
    falls back to the user's recently touched topics so prompts still
    have continuity."""

    # Pre-populate a recent topic touched by an earlier capture.
    prev_cap = _insert_screenshot_capture(rin_db / "prev")
    with session() as s:
        recent = Bucket(skill_name="topic", key="Recent", title="Recent")
        s.add(recent)
        s.flush()
        s.add(CaptureBucket(capture_id=prev_cap, bucket_id=recent.id))

    cap_id = _insert_screenshot_capture(rin_db / "new")
    cfg = _topic_cfg([{"name": "Recent", "keywords": ["yyy"]}])
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "rin.skills.pipeline.classify_capture",
        lambda *a, **kw: [],  # no detection this round
    )

    def fake_build_summary(capture: Capture, **kwargs) -> str:
        seen.update(kwargs)
        return "brief"

    monkeypatch.setattr(summarizer_module, "build_summary", fake_build_summary)

    analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda path, provider=None: ImageAnalysis(summary="hi", text="ocr"),
    )

    assert seen["active_pois"] == ["Recent"]


def test_analyze_capture_caps_active_pois_at_5(
    rin_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safety net: prompt never lists more than 5 POIs even if classify
    returned more (e.g. capture really did touch 10 topics)."""

    cap_id = _insert_screenshot_capture(rin_db / "capture")
    cfg = _topic_cfg([{"name": f"POI-{i}"} for i in range(10)])
    seen: dict[str, object] = {}

    def fake_classify(capture_id, _cfg, **kwargs):  # noqa: ARG001
        ids: list[int] = []
        with session() as s:
            for i in range(10):
                b = Bucket(skill_name="topic", key=f"POI-{i}", title=f"POI-{i}")
                s.add(b)
                s.flush()
                ids.append(b.id)
                s.add(CaptureBucket(capture_id=capture_id, bucket_id=b.id))
        return ids

    monkeypatch.setattr("rin.skills.pipeline.classify_capture", fake_classify)
    monkeypatch.setattr(
        summarizer_module,
        "build_summary",
        lambda cap, **kw: (seen.update(kw) or "brief"),
    )

    analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda path, provider=None: ImageAnalysis(summary="x", text="y"),
    )

    assert len(seen["active_pois"]) == 5

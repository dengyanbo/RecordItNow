from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import rin.analysis.summarizer as summarizer_module
from rin import paths as paths_mod
from rin.analysis.summarizer import _active_topic_names, analyze_capture, build_summary
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.storage import db, init_db, session
from rin.storage.models import Capture, CaptureFile
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
    assert "currently tracking these topics" not in provider.prompts[0]


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
        "The user is currently tracking these topics: Project Atlas, Customer Ops, "
        "Sprint Planning. If any of these are visible, mention them explicitly.\n"
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


def test_analyze_capture_passes_active_pois_to_build_summary(
    rin_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap_id = _insert_screenshot_capture(rin_db / "capture")
    cfg = _topic_cfg([{"name": "MyTopic", "keywords": ["topic"]}])
    seen: dict[str, object] = {}

    def fake_build_summary(capture: Capture, **kwargs) -> str:
        seen["capture_id"] = capture.id
        seen.update(kwargs)
        return "brief"

    monkeypatch.setattr(summarizer_module, "build_summary", fake_build_summary)
    monkeypatch.setattr("rin.skills.pipeline.classify_capture", lambda *args, **kwargs: [])

    aid = analyze_capture(
        cap_id,
        cfg,
        image_analyzer_fn=lambda path, provider=None: ImageAnalysis(summary="hello", text="ocr"),
    )

    assert isinstance(aid, int)
    assert seen["capture_id"] == cap_id
    assert seen["active_pois"] == ["MyTopic"]

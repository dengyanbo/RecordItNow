"""Phase 1-A: classify_capture wires the provider into TopicSkill so its
``llm_judge`` tier actually fires when a topic opts in.

Pre-Phase-A, ``TopicSkill.set_provider`` existed but was never invoked
in production. A topic with ``llm_judge=true`` would silently fall
through to ``_MISSING_PROVIDER_WARNING``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.skills.builtin.topic.skill import SKILL as TOPIC_SKILL
from rin.skills.builtin.topic.skill import TopicConfig, TopicSkill, TopicSpec
from rin.skills.pipeline import classify_capture
from rin.skills.registry import LoadedSkill
from rin.storage import db, init_db, session
from rin.storage.models import Bucket, Capture, CaptureFile


class JudgeProvider(Provider):
    name = "judge-fake"

    def __init__(self, reply: str = "YES") -> None:
        self.prompts: list[str] = []
        self.reply = reply

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis:
        raise NotImplementedError

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return self.reply

    def chat(self, messages):
        raise NotImplementedError


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    # Wipe the singleton-bound provider between tests so the global
    # TOPIC_SKILL doesn't carry state across cases.
    TOPIC_SKILL.set_provider(None)
    yield tmp_path
    TOPIC_SKILL.set_provider(None)
    db.reset()
    paths_mod.reset_cache()


def _insert_capture() -> int:
    with session() as s:
        cap = Capture(
            kind="screenshot",
            status="captured",
            folder="/tmp/x",
            started_at=datetime(2026, 6, 9, 12, 0, 0),
            ended_at=datetime(2026, 6, 9, 12, 0, 1),
        )
        cap.files = [
            CaptureFile(
                monitor_index=1,
                path="/tmp/x/m1.png",
                media_type="image/png",
                width=10,
                height=10,
            )
        ]
        s.add(cap)
        s.flush()
        return cap.id


def test_classify_capture_attaches_provider_to_topic_skill(rin_db: Path) -> None:
    """``classify_capture(..., provider=p)`` calls ``set_provider`` on every
    enabled skill that exposes it, so TopicSkill's llm_judge tier sees
    the provider and emits a bucket on YES."""

    cap_id = _insert_capture()
    cfg = RinConfig.model_validate({"skills": {"enabled": ["topic"]}})

    spec = TopicSpec(
        name="EdgeCase",
        description="A topic that only the LLM can recognize",
        keywords=[],
        regex=[],
        llm_judge=True,
    )
    skill = TopicSkill(TopicConfig(topics=[spec]))
    loaded = LoadedSkill(skill=skill, source="builtin", source_path="test")
    provider = JudgeProvider(reply="YES")

    bucket_ids = classify_capture(
        cap_id,
        cfg,
        summary="",
        ocr_text="some ambiguous content",
        transcript="",
        skills=[loaded],
        provider=provider,
    )

    assert bucket_ids, "topic skill should emit a bucket when llm_judge says YES"
    with session() as s:
        b = s.get(Bucket, bucket_ids[0])
    assert b is not None
    assert b.skill_name == "topic"
    assert b.title == "EdgeCase"
    # Provider got invoked — proves set_provider() was wired.
    assert provider.prompts, "JudgeProvider should have been invoked by topic.llm_judge"
    assert "EdgeCase" in provider.prompts[0]


def test_classify_capture_no_provider_does_not_crash_when_skill_lacks_setter(
    rin_db: Path,
) -> None:
    """A skill without ``set_provider`` (e.g. ``support_ticket``) is
    untouched. Pipeline still runs."""

    from rin.skills.base import BucketRef, Skill, SkillContext

    class DumbSkill(Skill):
        name = "dumb"

        def detect(self, ctx: SkillContext) -> list[BucketRef]:
            return [BucketRef(key="x", title="X")]

    cap_id = _insert_capture()
    cfg = RinConfig.model_validate({"skills": {"enabled": ["dumb"]}})
    loaded = LoadedSkill(skill=DumbSkill(), source="builtin", source_path="test")

    ids = classify_capture(
        cap_id,
        cfg,
        summary="",
        ocr_text="x",
        skills=[loaded],
        provider=JudgeProvider(),  # provider supplied; skill ignores it
    )

    assert ids, "dumb skill should still produce a bucket"

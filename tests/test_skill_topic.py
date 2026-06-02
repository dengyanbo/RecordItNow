"""Unit tests for the bundled ``topic`` skill."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

import rin.skills.builtin.topic.skill as topic_skill_module
from rin.llm.base import ImageAnalysis, Provider, ProviderCapabilities
from rin.skills.base import CaptureInfo, SkillContext, _default_archive
from rin.skills.builtin.topic.skill import TopicConfig, TopicSkill, TopicSpec


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


class FakeBucket:
    def __init__(self, title: str, key: str | None = None) -> None:
        self.title = title
        self.key = key or title
        self.opened_at = datetime(2026, 5, 1, 9, 0)
        self.closed_at = None


def _ctx(
    *,
    summary: str = "",
    ocr_text: str = "",
    transcript_text: str = "",
    config: TopicConfig | None = None,
) -> SkillContext:
    return SkillContext(
        capture_id=1,
        capture_kind="screenshot",
        started_at=datetime(2026, 5, 1, 9, 0),
        summary=summary,
        ocr_text=ocr_text,
        transcript_text=transcript_text,
        config=config,
    )


def _cap(
    capture_id: int,
    when: datetime,
    *,
    summary: str = "",
    ocr_text: str = "",
    transcript_text: str = "",
) -> CaptureInfo:
    return CaptureInfo(
        capture_id=capture_id,
        started_at=when,
        summary=summary,
        ocr_text=ocr_text,
        transcript_text=transcript_text,
    )


def test_topic_spec_defaults_are_independent() -> None:
    left = TopicSpec(name="Left")
    right = TopicSpec(name="Right")

    left.keywords.append("atlas")

    assert left.keywords == ["atlas"]
    assert right.keywords == []
    assert left.keywords is not right.keywords


def test_topic_config_empty_detect_returns_no_buckets() -> None:
    skill = TopicSkill(config=TopicConfig())

    assert skill.detect(_ctx(summary="anything")) == []


def test_topic_detect_matches_regex_keyword_and_alias() -> None:
    regex_skill = TopicSkill(
        config=TopicConfig(topics=[TopicSpec(name="MyProject", regex=[r"PROJ-\d+"])])
    )
    keyword_skill = TopicSkill(
        config=TopicConfig(topics=[TopicSpec(name="Project Atlas", keywords=["atlas"])])
    )
    alias_skill = TopicSkill(
        config=TopicConfig(topics=[TopicSpec(name="Packages", aliases=["pkg"])])
    )

    regex_refs = regex_skill.detect(_ctx(ocr_text="see PROJ-42"))
    keyword_refs = keyword_skill.detect(_ctx(summary="Working on Project ATLAS today"))
    alias_refs = alias_skill.detect(_ctx(summary="updated the pkg"))

    assert len(regex_refs) == 1
    assert regex_refs[0].key == "MyProject"
    assert [ref.key for ref in keyword_refs] == ["Project Atlas"]
    assert [ref.key for ref in alias_refs] == ["Packages"]


def test_topic_detect_skips_bad_regex_and_keeps_other_specs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level("WARNING")
    warnings: list[str] = []
    monkeypatch.setattr(topic_skill_module.log, "warning", warnings.append)
    skill = TopicSkill(
        config=TopicConfig(
            topics=[
                TopicSpec(name="Broken", regex=[r"[invalid("]),
                TopicSpec(name="Atlas", keywords=["atlas"]),
            ]
        )
    )

    refs = skill.detect(_ctx(summary="Working on atlas rollout"))

    assert [ref.key for ref in refs] == ["Atlas"]
    assert any("skipping bad regex" in message for message in warnings)


def test_topic_detect_returns_multiple_matching_specs_and_deduplicates_same_spec() -> None:
    multi_skill = TopicSkill(
        config=TopicConfig(
            topics=[
                TopicSpec(name="Atlas", keywords=["atlas"]),
                TopicSpec(name="Rollout", aliases=["rollout"]),
            ]
        )
    )
    dedupe_skill = TopicSkill(
        config=TopicConfig(
            topics=[
                TopicSpec(
                    name="Atlas",
                    regex=[r"ATLAS-\d+"],
                    keywords=["atlas"],
                    aliases=["launch"],
                )
            ]
        )
    )

    multi_refs = multi_skill.detect(_ctx(summary="Atlas rollout is on track"))
    dedupe_refs = dedupe_skill.detect(
        _ctx(summary="Atlas launch prep", ocr_text="tracking ATLAS-42 today")
    )

    assert {ref.key for ref in multi_refs} == {"Atlas", "Rollout"}
    assert [ref.key for ref in dedupe_refs] == ["Atlas"]


def test_topic_should_close_on_closed_phrase_or_inactivity() -> None:
    now = datetime(2026, 5, 10, 12, 0)
    skill = TopicSkill(
        config=TopicConfig(
            topics=[
                TopicSpec(
                    name="Project Atlas",
                    archive_after_days=7,
                    closed_phrases=["project closed"],
                )
            ]
        )
    )
    bucket = FakeBucket("Project Atlas")

    closed_caps = [
        _cap(1, now - timedelta(days=1), summary="still working"),
        _cap(2, now, summary="project closed after rollout"),
    ]
    stale_caps = [
        _cap(3, now - timedelta(days=7), summary="last touch before archive"),
    ]

    assert skill.should_close(bucket, closed_caps, now) is True
    assert skill.should_close(bucket, stale_caps, now) is True


def test_topic_render_archive_falls_back_without_provider() -> None:
    skill = TopicSkill(config=TopicConfig(topics=[TopicSpec(name="Project Atlas")]))
    bucket = FakeBucket("Project Atlas")
    captures = [_cap(1, datetime(2026, 5, 1, 9, 0), summary="kickoff")]

    assert skill.render_archive(bucket, captures, provider=None) == _default_archive(bucket, captures)


def test_topic_render_archive_uses_provider_when_present() -> None:
    skill = TopicSkill(config=TopicConfig(topics=[TopicSpec(name="Project Atlas")]))
    bucket = FakeBucket("Project Atlas")
    captures = [
        _cap(1, datetime(2026, 5, 1, 9, 0), summary="kickoff"),
        _cap(2, datetime(2026, 5, 2, 10, 0), summary="decision made"),
    ]
    provider = FakeProvider("## Status\n- Active\n")

    md = skill.render_archive(bucket, captures, provider=provider)

    assert md.startswith("# Project Atlas")
    assert "## Status" in md
    assert provider.system_prompts == [
        "You write concise factual summaries of activity around a single topic."
    ]
    assert provider.prompts[0].index("cap-1") < provider.prompts[0].index("cap-2")


def test_topic_detect_llm_judge_yes_and_no() -> None:
    config = TopicConfig(
        topics=[
            TopicSpec(
                name="Project Atlas",
                description="Internal migration program",
                llm_judge=True,
            )
        ]
    )
    yes_skill = TopicSkill(config=config)
    no_skill = TopicSkill(config=config)
    yes_skill.set_provider(FakeProvider("YES"))
    no_skill.set_provider(FakeProvider("NO"))

    yes_refs = yes_skill.detect(_ctx(summary="Ambiguous update", config=config))
    no_refs = no_skill.detect(_ctx(summary="Ambiguous update", config=config))

    assert [ref.key for ref in yes_refs] == ["Project Atlas"]
    assert no_refs == []


def test_topic_detect_llm_judge_skips_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(topic_skill_module.log, "warning", warnings.append)
    config = TopicConfig(topics=[TopicSpec(name="Project Atlas", llm_judge=True)])
    skill = TopicSkill(config=config)

    refs = skill.detect(_ctx(summary="Ambiguous update", config=config))

    assert refs == []
    assert any("no provider has been attached" in message for message in warnings)

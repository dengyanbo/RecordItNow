"""Tests for ``rin.skills.from_topic`` (Phase 3-B, v0.18.0)."""
from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

from rin.skills.builtin.topic.skill import TopicSpec
from rin.skills.from_topic import (
    _sanitise,
    convert_topic_to_skill,
    render_skill_source,
)
from rin.skills.scaffold import validate_skill

# ---------------------------------------------------------------------------
# _sanitise


def test_sanitise_basic() -> None:
    assert _sanitise("Project Atlas") == "project_atlas"
    assert _sanitise("Atlas v2.3") == "atlas_v2_3"
    assert _sanitise("ALL CAPS") == "all_caps"


def test_sanitise_leading_digit() -> None:
    assert _sanitise("2024 Q1") == "t_2024_q1"


def test_sanitise_empty_falls_back() -> None:
    assert _sanitise("...") == "topic"


# ---------------------------------------------------------------------------
# render_skill_source


def test_render_includes_topic_fields() -> None:
    topic = TopicSpec(
        name="Project Atlas",
        description="Internal rewrite",
        keywords=["atlas", "fulfillment"],
        regex=["ATL-\\d+"],
        aliases=["atlas rollout"],
        closed_phrases=["atlas shipped"],
        archive_after_days=14,
    )
    source = render_skill_source(topic)
    assert "name = 'project_atlas'" in source
    assert "display_name = 'Project Atlas'" in source
    assert "'atlas'" in source
    assert "'fulfillment'" in source
    assert "'ATL-\\\\d+'" in source
    assert "'atlas rollout'" in source
    assert "'atlas shipped'" in source
    assert "_ARCHIVE_AFTER_DAYS = 14" in source
    assert "class ProjectAtlasSkill(Skill):" in source
    assert "SKILL = ProjectAtlasSkill()" in source


def test_render_handles_empty_lists() -> None:
    topic = TopicSpec(name="Bare", description="", keywords=[])
    source = render_skill_source(topic)
    assert "_KEYWORDS = []" in source
    assert "_REGEX = []" in source
    assert "_ALIASES = []" in source
    assert "_CLOSED_PHRASES = []" in source


def test_render_is_deterministic() -> None:
    topic = TopicSpec(name="Same", keywords=["a", "b"])
    assert render_skill_source(topic) == render_skill_source(topic)


# ---------------------------------------------------------------------------
# convert_topic_to_skill


def test_convert_writes_file(tmp_path: Path) -> None:
    topic = TopicSpec(name="Project Beta", keywords=["beta"])
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    assert path == tmp_path / "project_beta" / "skill.py"
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "Project Beta" in body
    assert "'beta'" in body


def test_convert_refuses_overwrite_by_default(tmp_path: Path) -> None:
    topic = TopicSpec(name="dup", keywords=["x"])
    convert_topic_to_skill(topic, skills_dir=tmp_path)
    with pytest.raises(FileExistsError):
        convert_topic_to_skill(topic, skills_dir=tmp_path)


def test_convert_overwrite_replaces(tmp_path: Path) -> None:
    topic = TopicSpec(name="over", keywords=["a"])
    convert_topic_to_skill(topic, skills_dir=tmp_path)
    topic2 = TopicSpec(name="over", keywords=["b"])
    path = convert_topic_to_skill(topic2, skills_dir=tmp_path, overwrite=True)
    body = path.read_text(encoding="utf-8")
    assert "'b'" in body
    assert "'a'" not in body


def test_generated_skill_validates(tmp_path: Path) -> None:
    """Every generated skill should pass the v0.17 validator."""
    topic = TopicSpec(
        name="Validates",
        description="Should pass validator",
        keywords=["val", "vali"],
        regex=["VAL-\\d+"],
        aliases=["validation"],
        closed_phrases=["case closed"],
        archive_after_days=21,
    )
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    report = validate_skill(path)
    assert report.passed, report.format()


def test_generated_skill_detects_keyword(tmp_path: Path) -> None:
    """The generated detect() should fire on a keyword match."""
    import importlib.util
    from datetime import datetime

    from rin.skills.base import SkillContext

    topic = TopicSpec(name="Atlas", keywords=["atlas"])
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    spec = importlib.util.spec_from_file_location("gen_atlas", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ctx = SkillContext(
        capture_id=1,
        capture_kind="screenshot",
        started_at=datetime.now(UTC),
        summary="Working on Atlas today",
        ocr_text="",
        transcript_text="",
        window_titles=(),
        config=None,
    )
    result = mod.SKILL.detect(ctx)
    assert len(result) == 1
    assert result[0].key == "atlas"
    assert result[0].title == "Atlas"


def test_generated_skill_detects_regex(tmp_path: Path) -> None:
    import importlib.util
    from datetime import datetime

    from rin.skills.base import SkillContext

    topic = TopicSpec(name="Tickets", regex=["TKT-\\d+"], keywords=[])
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    spec = importlib.util.spec_from_file_location("gen_tickets", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ctx = SkillContext(
        capture_id=1,
        capture_kind="screenshot",
        started_at=datetime.now(UTC),
        summary="",
        ocr_text="See ticket TKT-12345 for details",
        transcript_text="",
        window_titles=(),
        config=None,
    )
    result = mod.SKILL.detect(ctx)
    assert len(result) == 1


def test_generated_skill_closes_on_phrase(tmp_path: Path) -> None:
    import importlib.util
    from datetime import datetime, timedelta

    from rin.skills.base import CaptureInfo

    topic = TopicSpec(
        name="Closeable",
        keywords=["foo"],
        closed_phrases=["all done"],
    )
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    spec = importlib.util.spec_from_file_location("gen_close", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    now = datetime.now(UTC)
    captures = [
        CaptureInfo(
            capture_id=1,
            started_at=now - timedelta(hours=1),
            summary="status: all done",
            ocr_text="",
            transcript_text="",
            file_paths=(),
        )
    ]
    assert mod.SKILL.should_close(None, captures, now) is True


def test_generated_skill_closes_on_age(tmp_path: Path) -> None:
    import importlib.util
    from datetime import datetime, timedelta

    from rin.skills.base import CaptureInfo

    topic = TopicSpec(
        name="Aged",
        keywords=["x"],
        archive_after_days=7,
    )
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    spec = importlib.util.spec_from_file_location("gen_aged", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    now = datetime.now(UTC)
    old_captures = [
        CaptureInfo(
            capture_id=1,
            started_at=now - timedelta(days=10),
            summary="nothing closed",
            ocr_text="",
            transcript_text="",
            file_paths=(),
        )
    ]
    assert mod.SKILL.should_close(None, old_captures, now) is True

    fresh_captures = [
        CaptureInfo(
            capture_id=2,
            started_at=now - timedelta(days=1),
            summary="nothing closed",
            ocr_text="",
            transcript_text="",
            file_paths=(),
        )
    ]
    assert mod.SKILL.should_close(None, fresh_captures, now) is False

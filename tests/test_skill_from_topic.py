"""Tests for ``rin.skills.from_topic`` (Phase 3-B, v0.18.0)."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from rin.skills.base import CaptureInfo, SkillContext
from rin.skills.builtin.topic.skill import TopicSpec
from rin.skills.from_topic import (
    _sanitise,
    convert_topic_to_skill,
    render_skill_source,
)
from rin.skills.scaffold import validate_skill


def test_sanitise_covers_common_cases() -> None:
    cases = [
        ("Project Atlas", "project_atlas"),
        ("Atlas v2.3", "atlas_v2_3"),
        ("ALL CAPS", "all_caps"),
        ("2024 Q1", "t_2024_q1"),  # leading digit → t_ prefix
        ("...", "topic"),            # no alphanumerics → fallback
    ]
    for name, expected in cases:
        assert _sanitise(name) == expected, f"{name!r} → got {_sanitise(name)!r}"


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
    for marker in [
        "name = 'project_atlas'",
        "display_name = 'Project Atlas'",
        "'atlas'", "'fulfillment'", "'ATL-\\\\d+'",
        "'atlas rollout'", "'atlas shipped'",
        "_ARCHIVE_AFTER_DAYS = 14",
        "class ProjectAtlasSkill(Skill):",
        "SKILL = ProjectAtlasSkill()",
    ]:
        assert marker in source, f"missing: {marker!r}"


def test_convert_writes_file_and_refuses_overwrite(tmp_path: Path) -> None:
    topic = TopicSpec(name="Project Beta", keywords=["beta"])
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    assert path == tmp_path / "project_beta" / "skill.py"
    body = path.read_text(encoding="utf-8")
    assert "Project Beta" in body and "'beta'" in body

    with pytest.raises(FileExistsError):
        convert_topic_to_skill(topic, skills_dir=tmp_path)

    topic2 = TopicSpec(name="Project Beta", keywords=["new"])
    path2 = convert_topic_to_skill(topic2, skills_dir=tmp_path, overwrite=True)
    assert "'new'" in path2.read_text(encoding="utf-8")


def test_generated_skill_validates(tmp_path: Path) -> None:
    """Every generated skill should pass the v0.17 validator."""
    topic = TopicSpec(
        name="Validates",
        description="Should pass validator",
        keywords=["val"],
        regex=["VAL-\\d+"],
        aliases=["validation"],
        closed_phrases=["case closed"],
        archive_after_days=21,
    )
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    report = validate_skill(path)
    assert report.passed, report.format()


def _load(path: Path, mod_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ctx(text: str, *, source: str = "summary") -> SkillContext:
    return SkillContext(
        capture_id=1,
        capture_kind="screenshot",
        started_at=datetime.now(UTC),
        summary=text if source == "summary" else "",
        ocr_text=text if source == "ocr" else "",
        transcript_text="",
        window_titles=(),
        config=None,
    )


def test_generated_skill_detects_keyword_and_regex(tmp_path: Path) -> None:
    """Both detection paths fire: keyword match (in summary) and regex
    match (in OCR text)."""
    # Keyword path
    kw_topic = TopicSpec(name="Atlas", keywords=["atlas"])
    kw_path = convert_topic_to_skill(kw_topic, skills_dir=tmp_path)
    kw_mod = _load(kw_path, "gen_atlas")
    kw_result = kw_mod.SKILL.detect(_ctx("Working on Atlas today", source="summary"))
    assert len(kw_result) == 1 and kw_result[0].key == "atlas"

    # Regex path
    rx_topic = TopicSpec(name="Tickets", regex=["TKT-\\d+"], keywords=[])
    rx_path = convert_topic_to_skill(rx_topic, skills_dir=tmp_path)
    rx_mod = _load(rx_path, "gen_tickets")
    rx_result = rx_mod.SKILL.detect(_ctx("See TKT-12345 for details", source="ocr"))
    assert len(rx_result) == 1 and rx_result[0].key == "tickets"


def test_generated_skill_should_close(tmp_path: Path) -> None:
    """Both close paths fire: closed-phrase match and age-based; fresh
    capture without phrase stays open."""
    topic = TopicSpec(
        name="Closeable",
        keywords=["foo"],
        closed_phrases=["all done"],
        archive_after_days=7,
    )
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)
    mod = _load(path, "gen_close")
    now = datetime.now(UTC)

    def _cap(when: datetime, summary: str) -> CaptureInfo:
        return CaptureInfo(
            capture_id=1, started_at=when, summary=summary,
            ocr_text="", transcript_text="", file_paths=(),
        )

    # Closed-phrase: recent capture with phrase → close.
    assert mod.SKILL.should_close(
        None, [_cap(now - timedelta(hours=1), "status: all done")], now
    ) is True
    # Age: old capture without phrase → close.
    assert mod.SKILL.should_close(
        None, [_cap(now - timedelta(days=10), "nothing closed")], now
    ) is True
    # Fresh: recent capture without phrase → stay open.
    assert mod.SKILL.should_close(
        None, [_cap(now - timedelta(days=1), "nothing closed")], now
    ) is False


def test_generated_skill_tolerates_bad_regex(tmp_path: Path) -> None:
    """v0.18.3: a malformed regex in the source PoI should NOT make the
    generated module fail to import — it should be logged + skipped, so
    the remaining patterns keep firing (matches the source ``topic``
    engine's behavior at builtin/topic/skill.py:_compiled_patterns)."""
    topic = TopicSpec(
        name="Mixed Patterns",
        regex=["TKT-\\d+", "[unterminated"],  # 2nd is invalid
        keywords=[],
    )
    path = convert_topic_to_skill(topic, skills_dir=tmp_path)

    mod = _load(path, "gen_mixed")

    # Module loaded despite the bad regex, and the good one is compiled.
    assert len(mod._COMPILED_REGEX) == 1
    assert mod._COMPILED_REGEX[0].pattern == "TKT-\\d+"

    # The good pattern still fires on a matching capture.
    result = mod.SKILL.detect(_ctx("See TKT-99 today", source="ocr"))
    assert len(result) == 1 and result[0].key == "mixed_patterns"


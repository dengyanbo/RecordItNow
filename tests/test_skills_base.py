"""Tests for the skill plugin system: base types, registry, support_ticket."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from rin.config import RinConfig
from rin.skills.base import (
    BucketRef,
    CaptureInfo,
    Skill,
    SkillContext,
    _default_archive,
)
from rin.skills.builtin.support_ticket import SKILL as SUPPORT_TICKET_SKILL
from rin.skills.builtin.support_ticket import SupportTicketSkill
from rin.skills.registry import discover

# ---------------------------------------------------------------------------
# Base types
# ---------------------------------------------------------------------------


def test_bucket_ref_freezes_extra_default() -> None:
    a = BucketRef(key="A", title="A")
    b = BucketRef(key="B", title="B")
    a.extra["x"] = 1
    # Each ref must get its own dict — no shared default.
    assert b.extra == {}


def test_skill_context_is_frozen() -> None:
    ctx = SkillContext(
        capture_id=1, capture_kind="screenshot", started_at=datetime.now(),
        summary="s", ocr_text="o", transcript_text="",
    )
    # frozen dataclass → mutating any attribute raises FrozenInstanceError
    with pytest.raises(Exception):  # noqa: B017 - we want the broad guard
        ctx.capture_id = 99  # type: ignore[misc]


def test_default_archive_renders_chronologically() -> None:
    class FakeBucket:
        title = "INC0012345"
        key = "INC0012345"
        opened_at = datetime(2026, 5, 1, 9, 0)
        closed_at = datetime(2026, 5, 3, 17, 0)

    caps = [
        CaptureInfo(
            capture_id=42,
            started_at=datetime(2026, 5, 2, 10, 0),
            summary="middle",
            ocr_text="", transcript_text="",
        ),
        CaptureInfo(
            capture_id=41,
            started_at=datetime(2026, 5, 1, 9, 0),
            summary="first",
            ocr_text="", transcript_text="",
        ),
        CaptureInfo(
            capture_id=43,
            started_at=datetime(2026, 5, 3, 17, 0),
            summary="last",
            ocr_text="", transcript_text="",
        ),
    ]
    md = _default_archive(FakeBucket(), caps)
    # Chronological order
    assert md.index("cap-41") < md.index("cap-42") < md.index("cap-43")
    assert "**Captures:** 3" in md


# ---------------------------------------------------------------------------
# support_ticket skill
# ---------------------------------------------------------------------------


def _ctx(**overrides) -> SkillContext:
    return SkillContext(
        capture_id=overrides.get("capture_id", 1),
        capture_kind="screenshot",
        started_at=overrides.get("started_at", datetime.now()),
        summary=overrides.get("summary", ""),
        ocr_text=overrides.get("ocr_text", ""),
        transcript_text=overrides.get("transcript_text", ""),
        config=overrides.get("config", SupportTicketSkill.Config()),
    )


def test_support_ticket_detect_extracts_service_now_id() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    ctx = _ctx(summary="Working on INC0012345 for ACME login issue")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    assert any(r.key == "INC0012345" for r in refs)


def test_support_ticket_detect_multiple_ids_returns_unique_buckets() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    ctx = _ctx(
        summary="Investigating INC0012345 and reviewing CASE0001234 too",
        ocr_text="INC0012345 status updated",  # dup
    )
    keys = [r.key for r in SUPPORT_TICKET_SKILL.detect(ctx)]
    assert "INC0012345" in keys
    assert "CASE0001234" in keys
    # No duplicate INC despite appearing twice across summary+ocr
    assert keys.count("INC0012345") == 1


def test_support_ticket_detect_no_match_returns_empty() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    ctx = _ctx(summary="Random work on a JIRA card PROJ-42 unrelated")
    assert SUPPORT_TICKET_SKILL.detect(ctx) == []


def test_support_ticket_detect_numeric_case_id_gets_case_prefix() -> None:
    """16-digit numeric IDs default to a `Case` bucket-title prefix."""

    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    SUPPORT_TICKET_SKILL._compiled = []
    ctx = _ctx(summary="Working on 2606050030000773 for ACME login issue")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    assert len(refs) == 1
    assert refs[0].key == "2606050030000773"
    assert refs[0].title.startswith("Case 2606050030000773")


def test_support_ticket_detect_19_digit_task_id_gets_task_prefix() -> None:
    """19-digit numeric IDs default to a `Task` bucket-title prefix."""

    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    SUPPORT_TICKET_SKILL._compiled = []
    ctx = _ctx(summary="Updated 2606010050000901001 status: in progress")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    assert len(refs) == 1
    assert refs[0].key == "2606010050000901001"
    assert refs[0].title.startswith("Task 2606010050000901001")


def test_support_ticket_detect_19_digit_does_not_also_match_inner_16() -> None:
    """Word-boundary anchors prevent a 19-digit task ID from also
    producing a phantom 16-digit case bucket from its prefix."""

    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    SUPPORT_TICKET_SKILL._compiled = []
    ctx = _ctx(summary="Reviewing collab task 2606010050000901001 today.")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    keys = [r.key for r in refs]
    assert keys == ["2606010050000901001"]


def test_support_ticket_detect_mixed_case_and_task_in_same_capture() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    SUPPORT_TICKET_SKILL._compiled = []
    ctx = _ctx(
        summary=(
            "Touched case 2606050030000773 and follow-up task "
            "2606010050000901001 in the same review."
        )
    )
    refs = {r.key: r.title for r in SUPPORT_TICKET_SKILL.detect(ctx)}
    assert set(refs) == {"2606050030000773", "2606010050000901001"}
    assert refs["2606050030000773"].startswith("Case ")
    assert refs["2606010050000901001"].startswith("Task ")


def test_support_ticket_detect_user_override_drops_default_labels() -> None:
    """Overriding id_patterns without id_labels yields empty prefixes
    so legacy custom regexes don't get accidentally labelled `Task`."""

    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config(
        id_patterns=[r"\bJIRA-\d+\b"],
    )
    SUPPORT_TICKET_SKILL._compiled = []
    ctx = _ctx(summary="Working on JIRA-987 today.")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    assert len(refs) == 1
    # No prefix at all — the title is just the key (no leading "Task " /
    # "Case "/ etc.) because labels do not align with patterns.
    assert not refs[0].title.startswith(("Task ", "Case "))
    assert refs[0].title.startswith("JIRA-987")


def test_support_ticket_only_first_match_flag() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config(only_first_match=True)
    ctx = _ctx(summary="Touched INC0012345 and CASE0001234 in same session")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    assert len(refs) == 1


def test_support_ticket_should_close_closed_phrase() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config()
    caps = [
        CaptureInfo(
            capture_id=1, started_at=datetime.now() - timedelta(hours=2),
            summary="investigation", ocr_text="", transcript_text="",
        ),
        CaptureInfo(
            capture_id=2, started_at=datetime.now(),
            summary="root cause found. Status: Resolved.",
            ocr_text="", transcript_text="",
        ),
    ]

    class B:
        key = "INC0012345"
        opened_at = datetime.now() - timedelta(hours=2)

    assert SUPPORT_TICKET_SKILL.should_close(B(), caps, datetime.now()) is True


def test_support_ticket_should_close_inactivity_timeout() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config(
        auto_archive_after_days=7,
    )
    caps = [
        CaptureInfo(
            capture_id=1, started_at=datetime.now() - timedelta(days=10),
            summary="long ago, never closed phrase",
            ocr_text="", transcript_text="",
        ),
    ]

    class B:
        key = "INC0012345"
        opened_at = datetime.now() - timedelta(days=10)

    assert SUPPORT_TICKET_SKILL.should_close(B(), caps, datetime.now()) is True


def test_support_ticket_should_close_returns_false_when_fresh() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config(
        auto_archive_after_days=14,
    )
    caps = [
        CaptureInfo(
            capture_id=1, started_at=datetime.now() - timedelta(hours=1),
            summary="still investigating",
            ocr_text="", transcript_text="",
        ),
    ]

    class B:
        key = "INC0012345"
        opened_at = datetime.now() - timedelta(hours=1)

    assert SUPPORT_TICKET_SKILL.should_close(B(), caps, datetime.now()) is False


def test_support_ticket_render_archive_without_provider_uses_fallback() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config(use_llm_for_archive=True)

    class B:
        title = "INC0012345 — login failure"
        key = "INC0012345"
        opened_at = datetime(2026, 5, 1)
        closed_at = datetime(2026, 5, 3)

    caps = [
        CaptureInfo(
            capture_id=1, started_at=datetime(2026, 5, 1),
            summary="first",
            ocr_text="", transcript_text="",
        ),
    ]
    # provider=None falls through to the template path.
    md = SUPPORT_TICKET_SKILL.render_archive(B(), caps, provider=None)
    assert "INC0012345" in md
    assert "cap-1" in md


def test_bad_regex_in_config_is_skipped() -> None:
    SUPPORT_TICKET_SKILL.config = SUPPORT_TICKET_SKILL.Config(
        id_patterns=[r"[invalid(", r"INC\d{7}"],
    )
    # Force recompile by resetting cache.
    SUPPORT_TICKET_SKILL._compiled = []
    ctx = _ctx(summary="found INC0012345 today")
    refs = SUPPORT_TICKET_SKILL.detect(ctx)
    assert [r.key for r in refs] == ["INC0012345"]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_discover_finds_bundled_support_ticket() -> None:
    cfg = RinConfig()
    cfg.skills.enabled = ["support_ticket"]
    found = discover(cfg)
    names = [ls.skill.name for ls in found]
    assert "support_ticket" in names


def test_discover_validates_per_skill_config() -> None:
    cfg = RinConfig()
    cfg.skills.enabled = ["support_ticket"]
    # Inject a bogus skill section via the extras (the model accepts it
    # because SkillsConfig has extra="allow").
    cfg.skills.__pydantic_extra__["support_ticket"] = {
        "auto_archive_after_days": 3,
        "use_llm_for_archive": False,
    }
    loaded = discover(cfg)
    skill = next(ls.skill for ls in loaded if ls.skill.name == "support_ticket")
    assert skill.config.auto_archive_after_days == 3
    assert skill.config.use_llm_for_archive is False


def test_discover_loads_user_skill_from_drop_in_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Putting a folder with skill.py under skills_dir() is enough."""

    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    from rin import paths as paths_mod
    paths_mod.reset_cache()

    skills_root = tmp_path / "skills" / "demo"
    skills_root.mkdir(parents=True)
    (skills_root / "skill.py").write_text(
        '''
from rin.skills.base import BucketRef, Skill, SkillContext


class DemoSkill(Skill):
    name = "demo_drop_in"
    display_name = "Demo"
    version = "0.0.1"
    description = "Test skill"

    def detect(self, ctx: SkillContext) -> list[BucketRef]:
        return [BucketRef(key="X", title="X")]


SKILL = DemoSkill()
''',
        encoding="utf-8",
    )

    cfg = RinConfig()
    cfg.skills.enabled = ["demo_drop_in"]
    loaded = discover(cfg)
    names = [ls.skill.name for ls in loaded]
    assert "demo_drop_in" in names
    paths_mod.reset_cache()


def test_discover_skips_broken_user_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    from rin import paths as paths_mod
    paths_mod.reset_cache()

    broken = tmp_path / "skills" / "broken"
    broken.mkdir(parents=True)
    (broken / "skill.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    cfg = RinConfig()
    # Discovery must not raise.
    found = discover(cfg)
    # And every bundled skill should still be there.
    assert any(ls.skill.name == "support_ticket" for ls in found)
    paths_mod.reset_cache()


def test_skill_with_custom_config_class_validates() -> None:
    class MyCfg(BaseModel):
        threshold: int = 5

    class MySkill(Skill):
        name = "my_test_skill"
        display_name = "My"
        version = "0.0.1"
        description = "Test"
        Config = MyCfg

        def detect(self, ctx: SkillContext) -> list[BucketRef]:
            return []

    # Direct invocation (registry not involved).
    skill = MySkill(config=MyCfg(threshold=12))
    assert skill.config.threshold == 12

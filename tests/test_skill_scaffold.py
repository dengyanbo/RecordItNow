"""Tests for the Phase 3-A skill scaffold + validator (v0.17.0)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rin.skills.scaffold import (
    _resolve_skill_path,
    scaffold_skill,
    validate_skill,
)

# ---------------------------------------------------------------------------
# scaffold_skill


def test_scaffold_creates_runnable_skill(tmp_path: Path) -> None:
    path = scaffold_skill(
        "my_skill",
        display_name="My Skill",
        description="A test skill",
        version="0.1.0",
        skills_dir=tmp_path,
    )
    assert path.exists()
    assert path == tmp_path / "my_skill" / "skill.py"
    body = path.read_text(encoding="utf-8")
    assert 'name = "my_skill"' in body
    assert 'display_name = "My Skill"' in body
    assert "class MySkillSkill(Skill):" in body
    assert "SKILL = MySkillSkill()" in body


def test_scaffold_rejects_invalid_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid skill name"):
        scaffold_skill("InvalidName", skills_dir=tmp_path)
    with pytest.raises(ValueError):
        scaffold_skill("1_starts_with_digit", skills_dir=tmp_path)
    with pytest.raises(ValueError):
        scaffold_skill("has-dash", skills_dir=tmp_path)


def test_scaffold_refuses_overwrite_by_default(tmp_path: Path) -> None:
    scaffold_skill("dup", skills_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_skill("dup", skills_dir=tmp_path)


def test_scaffold_overwrite_flag_replaces(tmp_path: Path) -> None:
    scaffold_skill("over", skills_dir=tmp_path)
    p = scaffold_skill(
        "over",
        skills_dir=tmp_path,
        description="updated",
        overwrite=True,
    )
    assert "updated" in p.read_text(encoding="utf-8")


def test_scaffolded_skill_validates(tmp_path: Path) -> None:
    """The fresh template should pass every validator check."""
    path = scaffold_skill("fresh", skills_dir=tmp_path)
    report = validate_skill(path)
    assert report.passed, report.format()


# ---------------------------------------------------------------------------
# validate_skill — failure cases


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_validate_file_missing(tmp_path: Path) -> None:
    report = validate_skill(tmp_path / "nope.py")
    assert not report.passed
    assert report.checks[0].name == "file exists"
    assert not report.checks[0].passed


def test_validate_broken_import(tmp_path: Path) -> None:
    p = _write(tmp_path / "bad" / "skill.py", "import nonexistent_module_xyz\n")
    report = validate_skill(p)
    assert not report.passed
    import_check = next(c for c in report.checks if c.name == "import")
    assert not import_check.passed
    assert "ModuleNotFoundError" in import_check.detail or "ImportError" in import_check.detail


def test_validate_missing_skill_attr(tmp_path: Path) -> None:
    p = _write(tmp_path / "noskill" / "skill.py", "x = 42\n")
    report = validate_skill(p)
    assert not report.passed
    check = next(c for c in report.checks if c.name == "SKILL attribute")
    assert "not defined" in check.detail


def test_validate_skill_wrong_type(tmp_path: Path) -> None:
    p = _write(tmp_path / "wrong" / "skill.py", "SKILL = 'not a Skill'\n")
    report = validate_skill(p)
    assert not report.passed
    check = next(c for c in report.checks if c.name == "SKILL attribute")
    assert "expected Skill instance" in check.detail


def test_validate_detect_wrong_return(tmp_path: Path) -> None:
    body = """\
from rin.skills.base import Skill, SkillContext

class S(Skill):
    name = "s"
    display_name = "S"
    version = "0.1.0"
    description = "x"

    def detect(self, ctx: SkillContext):
        return "not a list"

SKILL = S()
"""
    p = _write(tmp_path / "wrongret" / "skill.py", body)
    report = validate_skill(p)
    assert not report.passed
    check = next(c for c in report.checks if c.name == "detect()")
    assert "expected list" in check.detail


def test_validate_detect_raises(tmp_path: Path) -> None:
    body = """\
from rin.skills.base import Skill, SkillContext

class S(Skill):
    name = "s"
    display_name = "S"
    version = "0.1.0"
    description = "x"

    def detect(self, ctx: SkillContext):
        raise RuntimeError("boom")

SKILL = S()
"""
    p = _write(tmp_path / "raises" / "skill.py", body)
    report = validate_skill(p)
    assert not report.passed
    check = next(c for c in report.checks if c.name == "detect()")
    assert "RuntimeError" in check.detail


def test_validate_metadata_empty(tmp_path: Path) -> None:
    body = """\
from rin.skills.base import Skill, SkillContext, BucketRef

class S(Skill):
    name = ""
    display_name = ""
    version = ""
    description = ""

    def detect(self, ctx: SkillContext):
        return []

SKILL = S()
"""
    p = _write(tmp_path / "empty" / "skill.py", body)
    report = validate_skill(p)
    assert not report.passed
    check = next(c for c in report.checks if c.name == "metadata")
    assert "empty fields" in check.detail


# ---------------------------------------------------------------------------
# _resolve_skill_path helper


def test_resolve_accepts_dir(tmp_path: Path) -> None:
    (tmp_path / "myskill").mkdir()
    (tmp_path / "myskill" / "skill.py").write_text("x = 1\n", encoding="utf-8")
    resolved = _resolve_skill_path(tmp_path / "myskill")
    assert resolved == tmp_path / "myskill" / "skill.py"


def test_resolve_accepts_file(tmp_path: Path) -> None:
    p = tmp_path / "skill.py"
    p.write_text("x = 1\n", encoding="utf-8")
    assert _resolve_skill_path(p) == p


# ---------------------------------------------------------------------------
# report formatting


def test_report_format_pass(tmp_path: Path) -> None:
    path = scaffold_skill("fmt", skills_dir=tmp_path)
    report = validate_skill(path)
    out = report.format()
    assert "PASS" in out
    assert "fmt" in out
    assert "✓" in out
    assert "FAIL" not in out


def test_report_format_fail(tmp_path: Path) -> None:
    p = _write(tmp_path / "fail" / "skill.py", "SKILL = 42\n")
    report = validate_skill(p)
    out = report.format()
    assert "FAIL" in out
    assert "✗" in out

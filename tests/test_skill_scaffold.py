"""Tests for the Phase 3-A skill scaffold + validator (v0.17.0)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rin.skills.scaffold import (
    _resolve_skill_path,
    scaffold_skill,
    validate_skill,
)


def test_scaffold_creates_runnable_skill(tmp_path: Path) -> None:
    path = scaffold_skill(
        "my_skill",
        display_name="My Skill",
        description="A test skill",
        version="0.1.0",
        skills_dir=tmp_path,
    )
    assert path == tmp_path / "my_skill" / "skill.py"
    body = path.read_text(encoding="utf-8")
    assert 'name = "my_skill"' in body
    assert 'display_name = "My Skill"' in body
    assert "class MySkillSkill(Skill):" in body
    assert "SKILL = MySkillSkill()" in body


def test_scaffold_rejects_invalid_names(tmp_path: Path) -> None:
    """Names must match [a-z][a-z0-9_]* so they're importable."""
    for bad_name in ["InvalidName", "1_starts_with_digit", "has-dash"]:
        with pytest.raises(ValueError, match="Invalid skill name"):
            scaffold_skill(bad_name, skills_dir=tmp_path)


def test_scaffold_overwrite_semantics(tmp_path: Path) -> None:
    scaffold_skill("dup", skills_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_skill("dup", skills_dir=tmp_path)
    p = scaffold_skill("dup", skills_dir=tmp_path, description="updated", overwrite=True)
    assert "updated" in p.read_text(encoding="utf-8")


def test_scaffolded_skill_validates(tmp_path: Path) -> None:
    """The fresh template should pass every validator check."""
    path = scaffold_skill("fresh", skills_dir=tmp_path)
    report = validate_skill(path)
    assert report.passed, report.format()


def test_validate_failure_modes(tmp_path: Path) -> None:
    """All 7 common authoring mistakes surface a structured failure."""
    cases: list[tuple[str, str, str, str]] = [
        # (folder, body, check_name, detail_fragment)
        ("import", "import nonexistent_module_xyz\n", "import", "Error"),
        ("noattr", "x = 42\n", "SKILL attribute", "not defined"),
        ("wrong", "SKILL = 'not a Skill'\n", "SKILL attribute", "expected Skill instance"),
        (
            "wrongret",
            "from rin.skills.base import Skill, SkillContext\n\n"
            "class S(Skill):\n"
            "    name = 's'\n    display_name = 'S'\n"
            "    version = '0.1.0'\n    description = 'x'\n\n"
            "    def detect(self, ctx):\n        return 'not a list'\n\n"
            "SKILL = S()\n",
            "detect()",
            "expected list",
        ),
        (
            "raises",
            "from rin.skills.base import Skill, SkillContext\n\n"
            "class S(Skill):\n"
            "    name = 's'\n    display_name = 'S'\n"
            "    version = '0.1.0'\n    description = 'x'\n\n"
            "    def detect(self, ctx):\n        raise RuntimeError('boom')\n\n"
            "SKILL = S()\n",
            "detect()",
            "RuntimeError",
        ),
        (
            "empty",
            "from rin.skills.base import Skill, SkillContext\n\n"
            "class S(Skill):\n"
            "    name = ''\n    display_name = ''\n"
            "    version = ''\n    description = ''\n\n"
            "    def detect(self, ctx):\n        return []\n\n"
            "SKILL = S()\n",
            "metadata",
            "empty fields",
        ),
    ]
    for folder, body, check_name, detail_fragment in cases:
        p = tmp_path / folder / "skill.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        report = validate_skill(p)
        assert not report.passed, f"{folder}: should have failed"
        check = next(c for c in report.checks if c.name == check_name)
        assert detail_fragment in check.detail, f"{folder}: {check.detail!r}"

    # File-missing case: caught before any other check runs.
    missing = validate_skill(tmp_path / "nope.py")
    assert not missing.passed
    assert missing.checks[0].name == "file exists"


def test_resolve_accepts_dir_or_file(tmp_path: Path) -> None:
    folder = tmp_path / "myskill"
    folder.mkdir()
    skill_py = folder / "skill.py"
    skill_py.write_text("x = 1\n", encoding="utf-8")
    assert _resolve_skill_path(folder) == skill_py
    assert _resolve_skill_path(skill_py) == skill_py


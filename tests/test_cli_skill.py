"""Tests for the `rin skill` CLI subcommands (Phase 3-A, v0.17.0)."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_skill_scaffold_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from rin.__main__ import main

    rc = main(
        [
            "skill",
            "scaffold",
            "cli_test",
            "--dir",
            str(tmp_path),
            "--display-name",
            "CLI Test",
            "--description",
            "Made by CLI",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Created skill template" in out
    skill_py = tmp_path / "cli_test" / "skill.py"
    assert skill_py.exists()
    assert 'name = "cli_test"' in skill_py.read_text(encoding="utf-8")


def test_skill_scaffold_cli_rejects_bad_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from rin.__main__ import main

    rc = main(
        [
            "skill",
            "scaffold",
            "BadName",
            "--dir",
            str(tmp_path),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "Invalid skill name" in err


def test_skill_validate_cli_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from rin.__main__ import main

    # Use scaffold to seed a known-good skill, then validate.
    rc = main(
        [
            "skill",
            "scaffold",
            "good",
            "--dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    capsys.readouterr()  # drain scaffold output

    rc = main(["skill", "validate", str(tmp_path / "good")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out


def test_skill_validate_cli_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from rin.__main__ import main

    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "skill.py").write_text(
        "SKILL = 'not a skill'\n", encoding="utf-8"
    )

    rc = main(["skill", "validate", str(tmp_path / "bad" / "skill.py")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out

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


def test_cli_subprocess_survives_cp1252_console(tmp_path: Path) -> None:
    """Regression (v0.18.2): CLI must not crash on Windows cmd.exe / cp1252.

    Before v0.18.2, ``rin skill scaffold`` printed ``→ Skills`` (U+2192)
    via stdout. Under cmd.exe with the default cp1252 codepage that
    raises ``UnicodeEncodeError`` and the subprocess exits non-zero
    (with the skill.py already created — so the user sees a confusing
    "Error" after the success line). The fix is in ``rin.__main__``
    where we now reconfigure ``sys.stdout``/``sys.stderr`` to UTF-8.

    The same regression existed for ``rin skill validate`` whose
    output uses ``✓``/``✗`` ticks.
    """
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["RIN_DATA_DIR"] = str(tmp_path)
    # Force the child to act as if it were attached to a cp1252 console.
    env["PYTHONIOENCODING"] = "cp1252:replace"

    target_dir = tmp_path / "scaffold_out"
    target_dir.mkdir()
    scaffold = subprocess.run(
        [
            sys.executable, "-m", "rin", "skill", "scaffold", "cp1252_demo",
            "--dir", str(target_dir), "--force",
        ],
        capture_output=True, text=True, encoding="cp1252", errors="replace",
        env=env, timeout=30,
    )
    assert scaffold.returncode == 0, (
        f"scaffold under cp1252 crashed: rc={scaffold.returncode}\n"
        f"STDOUT:{scaffold.stdout}\nSTDERR:{scaffold.stderr}"
    )
    skill_py = target_dir / "cp1252_demo" / "skill.py"
    assert skill_py.exists()

    validate = subprocess.run(
        [sys.executable, "-m", "rin", "skill", "validate", str(skill_py)],
        capture_output=True, text=True, encoding="cp1252", errors="replace",
        env=env, timeout=30,
    )
    assert validate.returncode == 0, (
        f"validate under cp1252 crashed: rc={validate.returncode}\n"
        f"STDOUT:{validate.stdout}\nSTDERR:{validate.stderr}"
    )

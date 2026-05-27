"""Filesystem helpers + free-space guard."""
from __future__ import annotations

from pathlib import Path

import pytest

from rin.storage import files as f


def test_new_session_dir_creates_path() -> None:
    p = f.new_session_dir("shot", timestamp="20260521-100000")
    assert p.is_dir()
    assert p.name == "20260521-100000-shot"


def test_free_space_gb_positive() -> None:
    assert f.free_space_gb() > 0


def test_has_enough_free_space_thresholds() -> None:
    # ~zero GB requirement should always pass; an absurdly large one should always fail.
    assert f.has_enough_free_space(0.0) is True
    assert f.has_enough_free_space(10**9) is False


def test_safe_remove_refuses_outside_captures(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    with pytest.raises(ValueError):
        f.safe_remove_dir(target)
    assert target.exists()


def test_safe_remove_removes_inside_captures() -> None:
    session_dir = f.new_session_dir("shot", timestamp="20260521-101010")
    (session_dir / "x.txt").write_text("hi")
    f.safe_remove_dir(session_dir)
    assert not session_dir.exists()

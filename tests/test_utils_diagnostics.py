"""Tests for the diagnostic-report builder."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from rin import paths
from rin.utils import diagnostics


@pytest.fixture()
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``paths.root_dir`` at a tmp directory and pre-create the
    standard sub-directories with a sprinkling of artefacts that look
    like a real RIN install."""

    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths.reset_cache()

    # Fake config + log + capture artefacts
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "rin.log").write_text("INFO — sample log line\n", encoding="utf-8")

    cfg_text = (
        "[llm]\n"
        'name = "openai"\n'
        'api_key = "sk-realsecret123456"\n'
        'model = "gpt-4o"\n'
        "[capture]\n"
        "audio_sample_rate = 48000\n"
    )
    (tmp_path / "config.toml").write_text(cfg_text, encoding="utf-8")

    captures = tmp_path / "captures" / "2026" / "05" / "28" / "shot-001"
    captures.mkdir(parents=True)
    (captures / "monitor-1.png").write_bytes(b"\x89PNG\r\n")
    (captures / "monitor-2.png").write_bytes(b"\x89PNG\r\n")
    rec = tmp_path / "captures" / "2026" / "05" / "28" / "rec-001"
    rec.mkdir(parents=True)
    (rec / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftyp")

    (tmp_path / "rin.db").write_bytes(b"SQLite format 3\x00")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "2026-05-28.md").write_text("# Daily\n", encoding="utf-8")
    (tmp_path / "chroma").mkdir()

    yield tmp_path

    paths.reset_cache()


def test_redact_config_text_blanks_only_sensitive_keys() -> None:
    src = (
        "[llm]\n"
        'name = "openai"\n'
        'api_key = "sk-realsecret"\n'
        'model = "gpt-4o"\n'
        '# api_key = "this is just a comment"\n'
    )
    out = diagnostics._redact_config_text(src)
    assert "sk-realsecret" not in out
    assert '<redacted>' in out
    # Non-sensitive keys are untouched
    assert 'name = "openai"' in out
    assert 'model = "gpt-4o"' in out
    # Comment lines preserved verbatim
    assert '# api_key = "this is just a comment"' in out


def test_redact_config_handles_indented_keys() -> None:
    src = '    secret = "abc"\n'
    out = diagnostics._redact_config_text(src)
    assert '"abc"' not in out
    assert '<redacted>' in out


def test_build_report_writes_zip_with_expected_members(isolated_root: Path) -> None:
    # Mock subprocess.run so test does not depend on ffmpeg / pip being installed.
    with patch.object(diagnostics, "_ffmpeg_version", return_value="ffmpeg fake 0.0"), \
         patch.object(diagnostics, "_pip_freeze", return_value="rin==0.4.0\n"), \
         patch.object(diagnostics, "_monitor_summary", return_value=[
             {"w": 1920, "h": 1080, "x": 0, "y": 0}
         ]):
        out = diagnostics.build_report()

    assert out.exists()
    assert out.suffix == ".zip"
    assert out.parent == isolated_root
    assert out.name.startswith("rin-diagnostic-")

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "config.toml.txt" in names
        assert "environment.json" in names
        assert "stats.json" in names
        assert "pip_freeze.txt" in names
        assert "README.txt" in names
        assert "logs/rin.log" in names

        # Verify the secret never made it through to the bundle
        config_blob = zf.read("config.toml.txt").decode("utf-8")
        assert "sk-realsecret123456" not in config_blob
        assert "<redacted>" in config_blob

        # Verify stats counts match what we wrote
        stats = json.loads(zf.read("stats.json"))
        assert stats["captures"]["png"] == 2
        assert stats["captures"]["mp4"] == 1
        assert stats["reports_count"] == 1
        assert stats["db_present"] is True
        assert stats["chroma_present"] is True

        # Verify environment block is well-formed
        env = json.loads(zf.read("environment.json"))
        assert env["rin_version"]
        assert env["python_version"]
        assert env["monitors"] == [{"w": 1920, "h": 1080, "x": 0, "y": 0}]


def test_build_report_tolerates_missing_config(isolated_root: Path) -> None:
    (isolated_root / "config.toml").unlink()

    with patch.object(diagnostics, "_ffmpeg_version", return_value="?"), \
         patch.object(diagnostics, "_pip_freeze", return_value=""), \
         patch.object(diagnostics, "_monitor_summary", return_value=[]):
        out = diagnostics.build_report()

    with zipfile.ZipFile(out) as zf:
        config_blob = zf.read("config.toml.txt").decode("utf-8")
        assert "not present" in config_blob


def test_build_report_tolerates_empty_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths.reset_cache()
    try:
        with patch.object(diagnostics, "_ffmpeg_version", return_value="?"), \
             patch.object(diagnostics, "_pip_freeze", return_value=""), \
             patch.object(diagnostics, "_monitor_summary", return_value=[]):
            out = diagnostics.build_report()
        # No exception, zip still has the stub config
        with zipfile.ZipFile(out) as zf:
            assert "stats.json" in zf.namelist()
            stats = json.loads(zf.read("stats.json"))
            assert stats["captures"]["png"] == 0
            assert stats["db_present"] is False
    finally:
        paths.reset_cache()


def test_collect_environment_includes_rin_version() -> None:
    env = diagnostics.collect_environment()
    assert env["app_name"] == "RIN"
    assert env["rin_version"]
    assert env["python_version"]


def test_capture_counts_walks_extensions(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    (captures / "a.png").write_bytes(b"\x89PNG")
    (captures / "b.png").write_bytes(b"\x89PNG")
    (captures / "c.mp4").write_bytes(b"\x00\x00\x00\x18ftyp")
    (captures / "d.unknown").write_bytes(b"x")

    counts = diagnostics._capture_counts(captures)
    assert counts["png"] == 2
    assert counts["mp4"] == 1
    assert counts["other"] == 1

"""Smoke tests for paths and config — no Qt or heavy deps required."""
from __future__ import annotations

from pathlib import Path

from rin import paths
from rin.config import RinConfig


def test_root_dir_honors_env_override(isolated_data_dir: Path) -> None:
    assert paths.root_dir() == isolated_data_dir


def test_standard_dirs_are_created() -> None:
    assert paths.captures_dir().is_dir()
    assert paths.logs_dir().is_dir()
    assert paths.reports_dir().is_dir()
    assert paths.chroma_dir().is_dir()
    assert paths.models_cache_dir().is_dir()


def test_db_and_config_paths_resolve_under_root(isolated_data_dir: Path) -> None:
    assert paths.db_path().parent == isolated_data_dir
    assert paths.config_path().parent == isolated_data_dir


def test_capture_session_dir_dated_layout() -> None:
    out = paths.capture_session_dir("20260521-141203", "shot")
    assert out.is_dir()
    assert out.name == "20260521-141203-shot"
    parts = out.relative_to(paths.captures_dir()).parts
    assert parts[:3] == ("2026", "05", "21")


def test_config_round_trip() -> None:
    cfg = RinConfig.load()
    assert paths.config_path().exists()
    cfg.trigger.key = "F12"
    cfg.trigger.source = "keyboard"
    cfg.save()
    reloaded = RinConfig.load()
    assert reloaded.trigger.key == "F12"
    assert reloaded.trigger.source == "keyboard"
    assert reloaded.trigger.hold_threshold_ms == 500


def test_config_defaults_are_sensible() -> None:
    cfg = RinConfig()
    assert cfg.trigger.hold_threshold_ms == 500
    assert cfg.storage.raw_retention_days == 30
    assert cfg.storage.keep_summaries_forever is True
    assert cfg.working_hours.start_hour < cfg.working_hours.end_hour
    assert cfg.llm.name == "copilot_cli"

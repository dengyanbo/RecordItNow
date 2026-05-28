"""Config round-trip coverage for the new Settings surface."""
from __future__ import annotations

from rin.config import RinConfig


def test_config_round_trip_analysis_fields() -> None:
    cfg = RinConfig.load()
    cfg.analysis.ocr_languages = ["en", "ja", "de"]
    cfg.analysis.whisper_model = "medium"
    cfg.save()

    reloaded = RinConfig.load()
    assert reloaded.analysis.ocr_languages == ["en", "ja", "de"]
    assert reloaded.analysis.whisper_model == "medium"



def test_config_round_trip_telemetry_fields() -> None:
    cfg = RinConfig.load()
    cfg.telemetry.enabled = True
    cfg.telemetry.dsn = "https://public@example.ingest.sentry.io/1"
    cfg.telemetry.environment = "staging"
    cfg.save()

    reloaded = RinConfig.load()
    assert reloaded.telemetry.enabled is True
    assert reloaded.telemetry.dsn == "https://public@example.ingest.sentry.io/1"
    assert reloaded.telemetry.environment == "staging"



def test_config_round_trip_first_run_flag() -> None:
    cfg = RinConfig.load()
    assert cfg.first_run_completed is False
    cfg.first_run_completed = True
    cfg.save()

    assert RinConfig.load().first_run_completed is True

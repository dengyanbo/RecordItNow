"""User-mutable runtime configuration for RIN.

Persisted as TOML at ``%LOCALAPPDATA%\\RIN\\config.toml``. Defaults are
conservative so the app launches on first run without prompting. Each
section maps to a pydantic model so the UI (Phase 4) can validate
incremental edits.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, Field

from . import paths


class TriggerBinding(BaseModel):
    """A single bound input source. Fields are source-dependent and may be empty."""

    source: Literal["keyboard", "mouse", "hid", "unset"] = "unset"
    key: str | None = None
    vendor_id: int | None = None
    product_id: int | None = None
    usage_page: int | None = None
    usage: int | None = None
    hold_threshold_ms: int = 500
    label: str | None = None


class WorkingHours(BaseModel):
    enabled: bool = True
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    start_hour: int = 9
    end_hour: int = 18
    idle_threshold_minutes: int = 10


class LLMProviderConfig(BaseModel):
    name: Literal["copilot_cli", "openai", "azure", "none"] = "copilot_cli"
    # Default: Claude Opus 4.7 with 1M context (internal-only) at high reasoning effort.
    # Override either field in config.toml or via the Settings dialog. For OpenAI/Azure
    # leave ``reasoning_effort`` empty — it's a Copilot-CLI-only flag.
    model: str = "claude-opus-4.7-1m-internal"
    reasoning_effort: Literal["", "none", "low", "medium", "high", "xhigh", "max"] = "high"
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    timeout_seconds: int = 60
    max_retries: int = 3


class AnalysisConfig(BaseModel):
    hourly_enabled: bool = True
    require_idle_or_offhours: bool = True
    keyframe_interval_seconds: int = 5
    whisper_model: str = "small"


class ReportsConfig(BaseModel):
    frequency: Literal["daily", "weekly", "off"] = "daily"
    deliver_via_notification: bool = True


class StorageConfig(BaseModel):
    raw_retention_days: int = 30
    keep_summaries_forever: bool = True
    min_free_space_gb: int = 1


class CaptureConfig(BaseModel):
    screenshot_format: Literal["png"] = "png"
    video_container: Literal["mp4"] = "mp4"
    video_codec: Literal["h264"] = "h264"
    audio_sample_rate: int = 48000
    audio_channels: int = 2
    # Name of a DirectShow audio input device to mux into video recordings.
    # Use the exact string returned by ``ffmpeg -list_devices true -f dshow -i dummy``
    # (e.g. ``"Microphone (Realtek Audio)"`` or ``"Stereo Mix (Realtek Audio)"``).
    # Leave None to record video only.
    audio_device: str | None = None


class UIConfig(BaseModel):
    """User-mutable UI / appearance settings (v0.3.0+)."""

    theme: Literal["light", "dark", "auto"] = "auto"
    accent: Literal["blue", "purple", "teal", "orange"] = "blue"
    density: Literal["compact", "comfortable"] = "comfortable"


class RinConfig(BaseModel):
    """Root configuration object persisted to ``config.toml``."""

    paused: bool = False
    autostart: bool = False
    trigger: TriggerBinding = Field(default_factory=TriggerBinding)
    working_hours: WorkingHours = Field(default_factory=WorkingHours)
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    model_config = {"extra": "ignore"}

    @classmethod
    def load(cls, path: Path | None = None) -> RinConfig:
        path = path or paths.config_path()
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return cls(**data)

    def save(self, path: Path | None = None) -> None:
        path = path or paths.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # TOML has no null type; drop optional fields whose value is None.
        payload = self.model_dump(mode="python", exclude_none=True)
        with path.open("wb") as fh:
            tomli_w.dump(payload, fh)

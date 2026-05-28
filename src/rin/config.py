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
    ocr_languages: list[str] = Field(default_factory=lambda: ["en", "ch_sim"])
    whisper_model: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"


class TelemetryConfig(BaseModel):
    enabled: bool = False
    dsn: str | None = None
    environment: str = "production"


class ReportsConfig(BaseModel):
    frequency: Literal["daily", "weekly", "off"] = "daily"
    deliver_via_notification: bool = True
    # Surface this in Settings → Reports from ui/settings_dialog.py (owned by Agent D).
    obsidian_vault_path: str | None = None


class StorageConfig(BaseModel):
    raw_retention_days: int = 30
    keep_summaries_forever: bool = True
    min_free_space_gb: int = 1


class PrivacyConfig(BaseModel):
    app_blacklist: list[str] = Field(default_factory=list)
    paused_until_iso: str | None = None


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
    # TODO(Agent D): surface these post-screenshot quick-note controls in
    # Settings → Capture.
    enable_quick_note: bool = False
    quick_note_seconds: int = 5
    quick_note_audio_device: str | None = None


class UIConfig(BaseModel):
    """User-mutable UI / appearance settings (v0.3.0+)."""

    theme: Literal["light", "dark", "auto"] = "auto"
    accent: Literal["blue", "purple", "teal", "orange"] = "blue"
    density: Literal["compact", "comfortable"] = "comfortable"


class SkillsConfig(BaseModel):
    """Skill plugin system (v0.5.0+).

    Each skill has a stable ``name`` and registers itself with
    :mod:`rin.skills.registry`. ``enabled`` lists the names that should
    be active; everything else is discovered but inert.

    Per-skill configuration is written as nested TOML tables, e.g.::

        [skills]
        enabled = ["support_ticket"]
        closure_check_hours = 6

        [skills.support_ticket]
        id_patterns = ["INC\\d{7}", "REQ\\d{7}"]
        auto_archive_after_days = 14

    The ``[skills.support_ticket]`` table is collected into
    :attr:`model_extra` (Pydantic v2 ``extra="allow"``) so the static
    schema does not have to know about every installed skill at import
    time. The skill registry pulls each section out via
    :meth:`config_for_skill` and validates it against the skill's own
    ``Config`` Pydantic schema.
    """

    enabled: list[str] = Field(default_factory=list)
    # Where user-installed skills live. None = use paths.skills_dir().
    user_skills_dir: str | None = None
    # How often :class:`~rin.skills.scheduler.BucketScheduler` checks
    # active buckets for closure (hours). Lower = faster archive but
    # slightly more I/O. 6h is a sane balance.
    closure_check_hours: int = 6

    model_config = {"extra": "allow"}

    def config_for_skill(self, name: str) -> dict | None:
        """Return the raw TOML dict for ``[skills.<name>]`` or ``None``.

        Used by :func:`rin.skills.registry.discover` to seed each
        :class:`~rin.skills.base.Skill` with its validated config.
        """

        extras = self.model_extra or {}
        section = extras.get(name)
        if isinstance(section, dict):
            return section
        return None


class RinConfig(BaseModel):
    """Root configuration object persisted to ``config.toml``."""

    paused: bool = False
    autostart: bool = False
    first_run_completed: bool = False
    trigger: TriggerBinding = Field(default_factory=TriggerBinding)
    working_hours: WorkingHours = Field(default_factory=WorkingHours)
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    # TODO(Agent D): surface privacy blacklist + timed pause state in
    # Settings → Privacy.
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)

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

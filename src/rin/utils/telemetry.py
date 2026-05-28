"""Optional Sentry telemetry bootstrap."""
from __future__ import annotations

import importlib

from .. import __version__
from ..config import TelemetryConfig
from .logging import get_logger

log = get_logger(__name__)


def install(cfg: TelemetryConfig) -> bool:
    """Best-effort Sentry SDK setup. Returns True when telemetry is active."""

    if not cfg.enabled:
        return False

    dsn = (cfg.dsn or "").strip()
    if not dsn:
        log.warning("Telemetry enabled but DSN missing; skipping Sentry install")
        return False

    try:
        sentry_sdk = importlib.import_module("sentry_sdk")
    except ImportError:
        log.warning("sentry-sdk not installed; telemetry disabled")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=cfg.environment,
            release=f"rin@{__version__}",
        )
    except Exception as exc:
        log.warning(f"Sentry install skipped: {exc}")
        return False

    log.info("Sentry telemetry installed")
    return True

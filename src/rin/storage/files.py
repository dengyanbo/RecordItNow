"""Capture-file helpers and free-space guard.

Path resolution lives in :mod:`rin.paths`; this module adds capture-aware
utilities (timestamped session folders, disk-full guard, safe recursive
delete that refuses to touch anything outside the captures root).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .. import paths


def now_timestamp() -> str:
    """Return ``YYYYMMDD-HHMMSS`` for the current local time."""

    return datetime.now().strftime("%Y%m%d-%H%M%S")


def new_session_dir(kind: str, *, timestamp: str | None = None) -> Path:
    """Allocate a fresh capture-session directory under ``captures/YYYY/MM/DD/``."""

    ts = timestamp or now_timestamp()
    return paths.capture_session_dir(ts, kind)


def free_space_gb(target: Path | None = None) -> float:
    """Free space on the volume containing ``target`` (default: captures root)."""

    p = target or paths.captures_dir()
    p.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(str(p)).free / (1024**3)


def has_enough_free_space(min_gb: float, target: Path | None = None) -> bool:
    return free_space_gb(target) >= min_gb


def safe_remove_dir(p: Path) -> None:
    """Recursively delete ``p`` only if it lives inside the captures root."""

    captures_root = paths.captures_dir().resolve()
    try:
        resolved = p.resolve(strict=False)
    except OSError:
        return
    if not resolved.is_relative_to(captures_root):
        raise ValueError(f"Refusing to delete {p}: outside captures root {captures_root}")
    shutil.rmtree(resolved, ignore_errors=True)

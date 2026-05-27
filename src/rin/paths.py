"""Filesystem locations used by RIN.

All paths resolve under ``%LOCALAPPDATA%\\RIN`` on Windows by default. The
``RIN_DATA_DIR`` environment variable overrides the root, which tests use
to redirect into a tmp directory. ``*_dir()`` helpers create the
directory on first access; ``*_path()`` helpers do not.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs

from . import __app_name__

_DIRS = PlatformDirs(appname=__app_name__, appauthor=False, roaming=False)
_ENV_OVERRIDE = "RIN_DATA_DIR"


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache(maxsize=1)
def root_dir() -> Path:
    """Top-level RIN data directory. Honors ``RIN_DATA_DIR`` for tests."""

    override = os.environ.get(_ENV_OVERRIDE)
    root = Path(override) if override else Path(_DIRS.user_data_dir)
    return _ensure(root)


def reset_cache() -> None:
    """Clear the cached ``root_dir`` value. Tests call this after monkeypatching env."""

    root_dir.cache_clear()


def captures_dir() -> Path:
    return _ensure(root_dir() / "captures")


def logs_dir() -> Path:
    return _ensure(root_dir() / "logs")


def reports_dir() -> Path:
    return _ensure(root_dir() / "reports")


def chroma_dir() -> Path:
    return _ensure(root_dir() / "chroma")


def models_cache_dir() -> Path:
    return _ensure(root_dir() / "models")


def db_path() -> Path:
    return root_dir() / "rin.db"


def config_path() -> Path:
    return root_dir() / "config.toml"


def capture_session_dir(timestamp: str, kind: str) -> Path:
    """Return ``captures/YYYY/MM/DD/<timestamp>-<kind>/`` and create it.

    ``timestamp`` is expected to be ``YYYYMMDD-HHMMSS``; ``kind`` is
    ``shot`` or ``rec``.
    """

    if len(timestamp) < 8 or "-" not in timestamp:
        raise ValueError(f"timestamp must look like YYYYMMDD-HHMMSS, got {timestamp!r}")
    yyyy, mm, dd = timestamp[0:4], timestamp[4:6], timestamp[6:8]
    return _ensure(captures_dir() / yyyy / mm / dd / f"{timestamp}-{kind}")

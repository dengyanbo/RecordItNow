"""Misc Windows-specific helpers."""
from __future__ import annotations

import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def app_data_dir() -> str:
    """Return ``%LOCALAPPDATA%`` on Windows; ``~/.local/share`` on other OSes."""

    import os
    from pathlib import Path

    if is_windows():
        return os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return str(Path.home() / ".local" / "share")

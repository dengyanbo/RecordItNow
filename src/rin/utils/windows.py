"""Backwards-compatible re-exports for Windows helpers."""
from __future__ import annotations

from ._platform_windows import app_data_dir, is_windows

__all__ = ["app_data_dir", "is_windows"]

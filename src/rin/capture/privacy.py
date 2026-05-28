"""Best-effort privacy gate for capture-time foreground-window checks."""
from __future__ import annotations

import fnmatch

from ..utils import platform_compat


def is_capture_allowed(blacklist: list[str]) -> bool:
    """Return False when the foreground app/title matches a blacklist pattern."""

    patterns = [item.strip().lower() for item in blacklist if item and item.strip()]
    if not patterns:
        return True
    try:
        title, process_name = _get_foreground_window_details()
    except Exception:
        return True
    haystacks = [value.lower() for value in (title, process_name, f"{process_name} {title}") if value]
    for pattern in patterns:
        for value in haystacks:
            if fnmatch.fnmatch(value, pattern) or pattern in value:
                return False
    return True


def _get_foreground_window_details() -> tuple[str, str]:
    return (
        platform_compat.get_foreground_window_title(),
        platform_compat.get_foreground_process_name(),
    )

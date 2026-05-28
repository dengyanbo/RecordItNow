"""Best-effort privacy gate for capture-time foreground-window checks."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

try:  # pragma: no cover - import availability depends on platform
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - exercised via monkeypatched helper in tests
    win32gui = None
    win32process = None


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
    if win32gui is None or win32process is None:
        return "", ""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return "", ""
    title = win32gui.GetWindowText(hwnd) or ""
    _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
    return title, _process_name_from_pid(pid)


def _process_name_from_pid(pid: int) -> str:
    if os.name != "nt":
        return ""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        if not ok:
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)

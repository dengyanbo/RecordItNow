"""Windows implementations for :mod:`rin.utils.platform_compat`."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from .logging import get_logger
from .proc import no_window_kwargs

log = get_logger(__name__)

ThemeName = Literal["light", "dark"]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "RIN"
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

try:  # pragma: no cover - depends on host platform
    import winreg  # type: ignore[import]
except ImportError:  # pragma: no cover - exercised on non-Windows hosts
    winreg = None

try:  # pragma: no cover - depends on host platform
    import win32gui  # type: ignore[import]
    import win32process  # type: ignore[import]
except ImportError:  # pragma: no cover - exercised on non-Windows hosts
    win32gui = None
    win32process = None


def is_windows() -> bool:
    return sys.platform == "win32"


def _winreg():
    if not is_windows():
        return None
    return winreg


def app_data_dir() -> str:
    """Return ``%LOCALAPPDATA%`` on Windows; ``~/.local/share`` on other OSes."""

    if is_windows():
        return os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return str(Path.home() / ".local" / "share")


def list_audio_devices(binary: str = "ffmpeg", runner=None) -> list[str]:
    """Return DirectShow audio device names suitable for ffmpeg ``-f dshow``."""

    if not is_windows():
        return []
    if shutil.which(binary) is None and runner is None:
        return []

    runner = runner or subprocess.run
    try:
        proc = runner(
            [binary, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            **no_window_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning(f"ffmpeg device enumeration failed: {exc}")
        return []

    return _parse_dshow_audio_devices(proc.stderr or "")


def _parse_dshow_audio_devices(stderr: str) -> list[str]:
    """Parse ffmpeg ``-list_devices`` stderr into a list of audio device names."""

    import re

    devices: list[str] = []
    seen: set[str] = set()
    in_audio_section = False
    name_re = re.compile(r'"([^"]+)"\s*(?:\(([^)]+)\))?')
    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if "directshow audio devices" in lower:
            in_audio_section = True
            continue
        if "directshow video devices" in lower:
            in_audio_section = False
            continue
        if "alternative name" in lower:
            continue
        match = name_re.search(line)
        if not match:
            continue
        name = match.group(1)
        kind = (match.group(2) or "").lower()
        is_audio = kind == "audio" or (in_audio_section and kind != "video")
        if is_audio and name not in seen:
            seen.add(name)
            devices.append(name)
    return devices


def get_system_theme() -> ThemeName:
    """Read the Windows app theme preference from the current-user registry."""

    reg = _winreg()
    if reg is None:
        return "light"
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, THEME_KEY, 0, reg.KEY_READ) as key:
            value, _ = reg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value else "dark"
    except OSError:
        return "light"


def is_autostart_enabled() -> bool:
    """Return whether RIN is registered in the current-user ``Run`` key."""

    reg = _winreg()
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            value, _ = reg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning(f"autostart.is_enabled query failed: {exc}")
        return False


def enable_autostart(command: str) -> bool:
    """Set the current-user ``Run`` key to launch RIN at Windows sign-in."""

    reg = _winreg()
    if reg is None:
        log.warning("autostart.enable: not on Windows")
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command)
        log.info(f"Autostart enabled: {command}")
        return True
    except OSError as exc:
        log.error(f"autostart.enable failed: {exc}")
        return False


def disable_autostart() -> bool:
    """Remove RIN from the current-user ``Run`` key."""

    reg = _winreg()
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            try:
                reg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                return True
        log.info("Autostart disabled")
        return True
    except OSError as exc:
        log.error(f"autostart.disable failed: {exc}")
        return False


def default_autostart_command() -> str:
    """Return the most sensible ``rin`` invocation for the current install."""

    if not is_windows():
        return f'"{sys.executable}" -m rin'
    candidate = Path(sys.executable).parent / "rin.exe"
    if candidate.exists():
        return f'"{candidate}"'
    return f'"{sys.executable}" -m rin'


def get_foreground_window_title() -> str:
    """Return the current foreground window title, or ``""`` when unavailable."""

    return _get_foreground_window_details()[0]


def get_foreground_process_name() -> str:
    """Return the current foreground process image name, or ``""`` when unavailable."""

    return _get_foreground_window_details()[1]


def _get_foreground_window_details() -> tuple[str, str]:
    if not is_windows() or win32gui is None or win32process is None:
        return "", ""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return "", ""
    title = win32gui.GetWindowText(hwnd) or ""
    _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
    return title, _process_name_from_pid(pid)


def _process_name_from_pid(pid: int) -> str:
    if not is_windows():
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


__all__ = [
    "RUN_KEY",
    "VALUE_NAME",
    "app_data_dir",
    "default_autostart_command",
    "disable_autostart",
    "enable_autostart",
    "get_foreground_process_name",
    "get_foreground_window_title",
    "get_system_theme",
    "is_autostart_enabled",
    "is_windows",
]

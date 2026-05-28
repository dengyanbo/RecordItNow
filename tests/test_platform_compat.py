from __future__ import annotations

import subprocess
import sys
import types

import pytest

from rin.utils import platform_compat

WINDOWS_AUDIO_LISTING = """\
ffmpeg version 8.1.1
[dshow @ 000001] \"Integrated Camera\" (video)
[dshow @ 000001]   Alternative name \"@device_pnp_...\"
[dshow @ 000001] \"Microphone (Realtek Audio)\" (audio)
[dshow @ 000001]   Alternative name \"@device_cm_...\"
[dshow @ 000001] \"Stereo Mix (Realtek Audio)\" (audio)
"""


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("win32", (True, False, False)),
        ("darwin", (False, True, False)),
        ("linux", (False, False, True)),
    ],
)
def test_platform_flags(monkeypatch: pytest.MonkeyPatch, platform_name: str, expected: tuple[bool, bool, bool]) -> None:
    monkeypatch.setattr(sys, "platform", platform_name)
    assert platform_compat.is_windows() is expected[0]
    assert platform_compat.is_macos() is expected[1]
    assert platform_compat.is_linux() is expected[2]


@pytest.mark.parametrize(
    ("platform_name", "module_attr", "devices", "theme", "title", "process"),
    [
        ("win32", "_platform_windows", ["win-device"], "dark", "Win Title", "win.exe"),
        ("darwin", "_platform_macos", ["mac-device"], "light", "Mac Title", "Finder"),
        ("linux", "_platform_linux", ["linux-device"], "dark", "Linux Title", "gnome-shell"),
    ],
)
def test_dispatchers_route_to_selected_backend(
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    module_attr: str,
    devices: list[str],
    theme: str,
    title: str,
    process: str,
) -> None:
    fake_backend = types.SimpleNamespace(
        list_audio_devices=lambda binary="ffmpeg", runner=None: devices,
        get_system_theme=lambda: theme,
        enable_autostart=lambda command: command == "rin",
        disable_autostart=lambda: True,
        get_foreground_window_title=lambda: title,
        get_foreground_process_name=lambda: process,
    )

    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr(platform_compat, module_attr, fake_backend)

    assert platform_compat.list_audio_devices() == devices
    assert platform_compat.get_system_theme() == theme
    assert platform_compat.enable_autostart("rin") is True
    assert platform_compat.disable_autostart() is True
    assert platform_compat.get_foreground_window_title() == title
    assert platform_compat.get_foreground_process_name() == process


def test_windows_audio_dispatch_uses_real_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def fake_run(args, **_kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=WINDOWS_AUDIO_LISTING)

    assert platform_compat.list_audio_devices(runner=fake_run) == [
        "Microphone (Realtek Audio)",
        "Stereo Mix (Realtek Audio)",
    ]

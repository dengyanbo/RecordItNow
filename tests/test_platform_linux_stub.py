from __future__ import annotations

from rin.utils import _platform_linux as linux


def test_linux_stub_returns_safe_defaults() -> None:
    assert linux.list_audio_devices() == []
    assert linux.list_audio_devices(binary="ffmpeg", runner=object()) == []
    assert linux.get_system_theme() == "light"
    assert linux.enable_autostart("rin") is False
    assert linux.disable_autostart() is False
    assert linux.get_foreground_window_title() == ""
    assert linux.get_foreground_process_name() == ""


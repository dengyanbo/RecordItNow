from __future__ import annotations

from rin.utils import _platform_macos as macos


def test_macos_stub_returns_safe_defaults() -> None:
    assert macos.list_audio_devices() == []
    assert macos.list_audio_devices(binary="ffmpeg", runner=object()) == []
    assert macos.get_system_theme() == "light"
    assert macos.enable_autostart("rin") is False
    assert macos.disable_autostart() is False
    assert macos.get_foreground_window_title() == ""
    assert macos.get_foreground_process_name() == ""


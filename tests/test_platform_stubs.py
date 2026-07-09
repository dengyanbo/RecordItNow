from __future__ import annotations

from types import ModuleType

import pytest

from rin.utils import _platform_linux as linux
from rin.utils import _platform_macos as macos


@pytest.mark.parametrize("platform_module", [linux, macos], ids=["linux", "macos"])
def test_platform_stub_returns_safe_defaults(platform_module: ModuleType) -> None:
    assert platform_module.list_audio_devices() == []
    assert platform_module.list_audio_devices(binary="ffmpeg", runner=object()) == []
    assert platform_module.get_system_theme() == "light"
    assert platform_module.enable_autostart("rin") is False
    assert platform_module.disable_autostart() is False
    assert platform_module.get_foreground_window_title() == ""
    assert platform_module.get_foreground_process_name() == ""

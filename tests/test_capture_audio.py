"""Tests for DirectShow audio device enumeration parsing."""
from __future__ import annotations

import subprocess

from rin.capture.audio import _parse_dshow_audio_devices, list_dshow_audio_devices

# Real-world FFmpeg output (slightly trimmed) — the format has changed twice
# in the last few years, so we test both shapes.

LEGACY_FORMAT = """\
ffmpeg version 6.1
[dshow @ 000001] "Integrated Camera"
[dshow @ 000001]   Alternative name "@device_pnp_..."
[dshow @ 000001] "USB Capture"
[dshow @ 000001] DirectShow audio devices
[dshow @ 000001] "Microphone (Realtek Audio)"
[dshow @ 000001]   Alternative name "@device_cm_..."
[dshow @ 000001] "Stereo Mix (Realtek Audio)"
"""

NEW_FORMAT = """\
ffmpeg version 8.1.1
[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_..."
[dshow @ 000001] "Microphone (Realtek Audio)" (audio)
[dshow @ 000001]   Alternative name "@device_cm_..."
[dshow @ 000001] "Stereo Mix (Realtek Audio)" (audio)
[dshow @ 000001]   Alternative name "@device_cm_..."
"""


def test_parse_legacy_section_format() -> None:
    devices = _parse_dshow_audio_devices(LEGACY_FORMAT)
    assert devices == ["Microphone (Realtek Audio)", "Stereo Mix (Realtek Audio)"]


def test_parse_new_inline_kind_format() -> None:
    devices = _parse_dshow_audio_devices(NEW_FORMAT)
    assert devices == ["Microphone (Realtek Audio)", "Stereo Mix (Realtek Audio)"]


def test_parse_handles_no_audio_devices() -> None:
    text = '[dshow] "Integrated Camera" (video)\n'
    assert _parse_dshow_audio_devices(text) == []


def test_parse_deduplicates_repeats() -> None:
    text = (
        '[dshow] "Microphone (Realtek)" (audio)\n'
        '[dshow] "Microphone (Realtek)" (audio)\n'
    )
    assert _parse_dshow_audio_devices(text) == ["Microphone (Realtek)"]


def test_list_dshow_audio_devices_uses_runner() -> None:
    """When a runner is injected, we don't need ffmpeg on PATH."""

    def fake_run(args, **_kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=NEW_FORMAT)

    devices = list_dshow_audio_devices(runner=fake_run)
    assert "Microphone (Realtek Audio)" in devices
    assert "Stereo Mix (Realtek Audio)" in devices


def test_list_dshow_audio_devices_swallows_timeout() -> None:
    def boom(args, **_kwargs):
        raise subprocess.TimeoutExpired(args, timeout=1)

    assert list_dshow_audio_devices(runner=boom) == []

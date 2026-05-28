from __future__ import annotations

import sys
import types
import wave
from pathlib import Path

import numpy as np

from rin.capture.audio import record_short_clip
from rin.capture.service import CaptureService
from rin.config import RinConfig


def test_record_short_clip_writes_16khz_mono_wav(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[int, int, int, str, str | None]] = []

    def rec(frames: int, *, samplerate: int, channels: int, dtype: str, device: str | None):
        calls.append((frames, samplerate, channels, dtype, device))
        return np.full((frames, channels), 123, dtype=np.int16)

    fake_sd = types.SimpleNamespace(rec=rec, wait=lambda: None)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    out = tmp_path / "quick_note.wav"
    assert record_short_clip(5, "Mic 1", out) == out
    assert calls == [(80_000, 16_000, 1, "int16", "Mic 1")]

    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16_000
        assert wf.getnframes() == 80_000


def test_take_screenshot_records_quick_note_when_enabled(monkeypatch, tmp_path: Path) -> None:
    cfg = RinConfig()
    cfg.capture.enable_quick_note = True
    cfg.capture.quick_note_seconds = 3
    cfg.capture.quick_note_audio_device = "Desk Mic"
    svc = CaptureService(cfg)

    recorded: list[tuple[int, str | None, Path]] = []
    monkeypatch.setattr("rin.capture.service.has_enough_free_space", lambda _min_gb: True)
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda _blacklist: True)
    monkeypatch.setattr("rin.capture.service.capture_screenshot", lambda **_kwargs: 77)
    monkeypatch.setattr(
        CaptureService,
        "_capture_folder_for",
        lambda self, capture_id: tmp_path if capture_id == 77 else None,
    )
    monkeypatch.setattr(
        "rin.capture.service.record_short_clip",
        lambda seconds, device, out_path: recorded.append((seconds, device, out_path)),
    )

    assert svc.take_screenshot() == 77
    assert recorded == [(3, "Desk Mic", tmp_path / "quick_note.wav")]

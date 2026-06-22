"""Tests for the recording backend selection (ddagrab vs gdigrab) and the
draw-cursor / cursor-flicker controls added in v1.2.0.

No real ffmpeg is invoked: the ddagrab probe's ``subprocess.run`` is
monkeypatched, and command construction is asserted on the argv list.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rin.capture import recorder as rec
from rin.capture.monitors import MonitorInfo
from rin.capture.recorder import (
    build_ffmpeg_command,
    ddagrab_available,
    select_backend,
)
from rin.config import CaptureConfig

_MON = MonitorInfo(index=1, name="monitor-1", x=0, y=0, width=1920, height=1080, is_primary=True)


def _cmd(**kwargs) -> list[str]:
    return build_ffmpeg_command(_MON, Path("out.mp4"), capture_cfg=CaptureConfig(), **kwargs)


# --- command construction -----------------------------------------------------


def test_ddagrab_command_uses_filtergraph_and_keeps_cursor() -> None:
    cmd = _cmd(backend="ddagrab", output_idx=2)
    joined = " ".join(cmd)
    assert "-filter_complex" in cmd
    assert "ddagrab=output_idx=2:framerate=30:draw_mouse=1" in joined
    assert "hwdownload,format=bgra[v]" in joined
    assert "gdigrab" not in joined
    # Software encode path is preserved.
    assert "libx264" in cmd
    assert cmd[-1] == "out.mp4"


def test_ddagrab_command_maps_audio_input() -> None:
    cmd = build_ffmpeg_command(
        _MON, Path("out.mp4"), capture_cfg=CaptureConfig(),
        backend="ddagrab", audio_device="Microphone (Realtek)",
    )
    joined = " ".join(cmd)
    assert "audio=Microphone (Realtek)" in joined
    assert "-map" in cmd and "[v]" in cmd
    assert "0:a" in cmd  # audio is input #0, mapped explicitly
    assert "aac" in cmd


def test_gdigrab_command_draw_mouse_on_by_default() -> None:
    cmd = _cmd(backend="gdigrab")
    assert "gdigrab" in cmd
    assert "-draw_mouse" in cmd
    assert cmd[cmd.index("-draw_mouse") + 1] == "1"


def test_gdigrab_command_draw_mouse_off_when_cursor_disabled() -> None:
    cfg = CaptureConfig(draw_cursor=False)
    cmd = build_ffmpeg_command(_MON, Path("out.mp4"), capture_cfg=cfg, backend="gdigrab")
    assert cmd[cmd.index("-draw_mouse") + 1] == "0"


def test_ddagrab_command_draw_mouse_off_when_cursor_disabled() -> None:
    cfg = CaptureConfig(draw_cursor=False)
    cmd = build_ffmpeg_command(_MON, Path("out.mp4"), capture_cfg=cfg, backend="ddagrab")
    assert "draw_mouse=0" in " ".join(cmd)


# --- probe + selection --------------------------------------------------------


def _fake_run(returncode: int):
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout="", stderr="")

    return runner


def test_ddagrab_available_true_when_probe_succeeds(monkeypatch) -> None:
    ddagrab_available.cache_clear()
    monkeypatch.setattr(rec, "ffmpeg_available", lambda binary="ffmpeg": True)
    monkeypatch.setattr(rec.subprocess, "run", _fake_run(0))
    assert ddagrab_available("ffmpeg") is True
    ddagrab_available.cache_clear()


def test_ddagrab_available_false_when_probe_fails(monkeypatch) -> None:
    # Mirrors the RDP / GPU-less VM case: device creation fails, rc != 0.
    ddagrab_available.cache_clear()
    monkeypatch.setattr(rec, "ffmpeg_available", lambda binary="ffmpeg": True)
    monkeypatch.setattr(rec.subprocess, "run", _fake_run(1))
    assert ddagrab_available("ffmpeg") is False
    ddagrab_available.cache_clear()


def test_ddagrab_available_false_when_ffmpeg_missing(monkeypatch) -> None:
    ddagrab_available.cache_clear()
    monkeypatch.setattr(rec, "ffmpeg_available", lambda binary="ffmpeg": False)

    def _boom(*a, **k):
        raise AssertionError("must not probe when ffmpeg is absent")

    monkeypatch.setattr(rec.subprocess, "run", _boom)
    assert ddagrab_available("ffmpeg") is False
    ddagrab_available.cache_clear()


def test_ddagrab_available_caches_probe(monkeypatch) -> None:
    ddagrab_available.cache_clear()
    monkeypatch.setattr(rec, "ffmpeg_available", lambda binary="ffmpeg": True)
    calls = {"n": 0}

    def counting(args, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rec.subprocess, "run", counting)
    ddagrab_available("ffmpeg")
    ddagrab_available("ffmpeg")
    assert calls["n"] == 1  # second call served from cache
    ddagrab_available.cache_clear()


@pytest.mark.parametrize(
    "requested,probe,expected",
    [
        ("gdigrab", True, "gdigrab"),   # forced
        ("ddagrab", False, "ddagrab"),  # forced even if probe would fail
        ("auto", True, "ddagrab"),
        ("auto", False, "gdigrab"),     # RDP / VM fallback
    ],
)
def test_select_backend(monkeypatch, requested, probe, expected) -> None:
    monkeypatch.setattr(rec, "ddagrab_available", lambda binary="ffmpeg": probe)
    cfg = CaptureConfig(video_backend=requested)
    assert select_backend(cfg, "ffmpeg") == expected


def test_recorder_uses_selected_backend(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rec, "ddagrab_available", lambda binary="ffmpeg": True)
    captured: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured.append(args)
            self.args = args
            self.pid = 4321
            self.stdin = None
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    recorder = rec.VideoRecorder(
        monitors=[_MON],
        folder=tmp_path / "rec",
        capture_cfg=CaptureConfig(video_backend="auto"),
        popen_factory=_FakePopen,
    )
    assert recorder.backend == "ddagrab"
    recorder.start()
    assert any("ddagrab=output_idx=0" in " ".join(a) for a in captured)

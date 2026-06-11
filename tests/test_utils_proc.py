"""Tests for the console-window suppression helper.

RIN is a windowed app; spawning console children (ffmpeg, copilot) on
Windows flashes a cmd window unless ``CREATE_NO_WINDOW`` is passed. The
helper must add that flag on Windows and stay a no-op elsewhere.
"""
from __future__ import annotations

import subprocess

from rin.utils import proc


def test_no_window_kwargs_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(proc.sys, "platform", "win32")
    kwargs = proc.no_window_kwargs()
    assert kwargs == {"creationflags": proc.CREATE_NO_WINDOW}
    assert "creationflags" in kwargs


def test_no_window_kwargs_off_windows_is_noop(monkeypatch) -> None:
    for platform_name in ("linux", "darwin"):
        monkeypatch.setattr(proc.sys, "platform", platform_name)
        assert proc.no_window_kwargs() == {}


def test_create_no_window_matches_stdlib_when_available() -> None:
    # On Windows the constant must equal the stdlib flag; elsewhere it
    # falls back to 0 so the module stays import-safe.
    expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert expected == proc.CREATE_NO_WINDOW

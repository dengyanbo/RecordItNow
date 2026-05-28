"""Tests for CaptureService.last_skip — context-aware skip reasons."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from rin.capture.service import CaptureService, SkipInfo
from rin.config import RinConfig


def _make_service(monkeypatch: pytest.MonkeyPatch) -> CaptureService:
    # Avoid touching disk: stub disk + privacy + monitors so we focus on
    # the skip-bookkeeping logic specifically.
    cfg = RinConfig()
    svc = CaptureService(cfg)
    svc._monitors = []
    monkeypatch.setattr("rin.capture.service.has_enough_free_space", lambda *a, **kw: True)
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda blk: True)
    return svc


def test_no_skip_after_init(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    assert svc.last_skip() is None


def test_skip_paused_records_reason_and_resume_time(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    until = datetime.now() + timedelta(minutes=15)
    svc.config.privacy.paused_until_iso = until.isoformat()

    result = svc.take_screenshot()
    assert result is None

    skip = svc.last_skip()
    assert skip is not None
    assert skip.reason == "paused"
    assert "Resumes at" in skip.detail
    assert until.strftime("%H:%M") in skip.detail


def test_skip_blacklist(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda blk: False)
    svc.config.privacy.app_blacklist = ["pwsafe"]

    result = svc.take_screenshot()
    assert result is None
    skip = svc.last_skip()
    assert skip is not None
    assert skip.reason == "blacklist"
    assert "privacy" in skip.detail.lower()


def test_skip_disk_full(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    monkeypatch.setattr("rin.capture.service.has_enough_free_space", lambda *a, **kw: False)

    result = svc.take_screenshot()
    assert result is None
    skip = svc.last_skip()
    assert skip is not None
    assert skip.reason == "disk_full"


def test_skip_capture_actual_failure_uses_exception_text(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    with patch("rin.capture.service.capture_screenshot", side_effect=RuntimeError("BitBlt fail")):
        result = svc.take_screenshot()
    assert result is None
    skip = svc.last_skip()
    assert skip is not None
    assert skip.reason == "failed"
    assert "BitBlt" in skip.detail


def test_skip_is_reset_on_successful_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    # First call: blacklisted
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda blk: False)
    svc.take_screenshot()
    assert svc.last_skip() is not None
    # Second call: succeeds
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda blk: True)
    with patch("rin.capture.service.capture_screenshot", return_value=42):
        cap_id = svc.take_screenshot()
    assert cap_id == 42
    assert svc.last_skip() is None


def test_skip_already_recording_on_double_start(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    # Simulate an already-active recording.
    svc._recorder = object()  # type: ignore[assignment]
    ok = svc.start_recording()
    assert ok is False
    skip = svc.last_skip()
    assert skip is not None
    assert skip.reason == "already_recording"


def test_skip_no_monitors(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _make_service(monkeypatch)
    svc._monitors = []
    monkeypatch.setattr("rin.capture.service.enumerate_monitors", lambda: [])
    ok = svc.start_recording()
    assert ok is False
    skip = svc.last_skip()
    assert skip is not None
    assert skip.reason == "no_monitors"


def test_skip_info_is_frozen() -> None:
    s = SkipInfo("paused", "Resumes at 17:06")
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass guard
        s.detail = "tampered"  # type: ignore[misc]

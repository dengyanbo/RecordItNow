from __future__ import annotations

from datetime import datetime, timedelta

from rin.capture import privacy
from rin.capture.service import CaptureService
from rin.config import RinConfig


def test_is_capture_allowed_blocks_matching_title_or_process(monkeypatch) -> None:
    monkeypatch.setattr(
        privacy,
        "_get_foreground_window_details",
        lambda: ("Quarterly Payroll Review", "Teams.exe"),
    )
    assert privacy.is_capture_allowed(["payroll", "notepad*"]) is False
    assert privacy.is_capture_allowed(["teams.exe"]) is False


def test_is_capture_allowed_returns_true_on_lookup_error(monkeypatch) -> None:
    def boom() -> tuple[str, str]:
        raise RuntimeError("win32 hiccup")

    monkeypatch.setattr(privacy, "_get_foreground_window_details", boom)
    assert privacy.is_capture_allowed(["confidential"]) is True


def test_take_screenshot_short_circuits_when_timed_pause_is_active(monkeypatch) -> None:
    cfg = RinConfig()
    cfg.privacy.paused_until_iso = (datetime.now() + timedelta(minutes=15)).isoformat()
    svc = CaptureService(cfg)

    monkeypatch.setattr("rin.capture.service.has_enough_free_space", lambda _min_gb: True)
    monkeypatch.setattr(
        "rin.capture.service.capture_screenshot",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("capture should be skipped")),
    )

    assert svc.take_screenshot() is None


def test_take_screenshot_short_circuits_when_privacy_blacklist_matches(monkeypatch) -> None:
    cfg = RinConfig()
    cfg.privacy.app_blacklist = ["secret*"]
    svc = CaptureService(cfg)

    monkeypatch.setattr("rin.capture.service.has_enough_free_space", lambda _min_gb: True)
    monkeypatch.setattr("rin.capture.service.is_capture_allowed", lambda _blacklist: False)
    monkeypatch.setattr(
        "rin.capture.service.capture_screenshot",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("capture should be skipped")),
    )

    assert svc.take_screenshot() is None

"""Tray-menu wiring tests for the in-app updater."""
from __future__ import annotations

from typing import Any

from rin.config import RinConfig
from rin.utils.updater import UpdateInfo


def _make_tray(qapp, cfg: RinConfig | None = None):
    from rin.ui.tray import TrayApp

    return TrayApp(cfg or RinConfig())


def test_tray_menu_includes_check_for_updates(qapp) -> None:
    tray = _make_tray(qapp)

    labels = [action.text() for action in tray._menu.actions() if not action.isSeparator()]

    assert any("Check for updates" in label for label in labels), labels


def test_startup_auto_check_respects_config_off(qapp, monkeypatch) -> None:
    from rin.ui import tray as tray_mod

    cfg = RinConfig()
    cfg.auto_check_updates = False
    tray = _make_tray(qapp, cfg)
    calls = 0

    def fake_check_for_update(**_: object) -> None:
        nonlocal calls
        calls += 1

    class FailingPool:
        def start(self, task: object) -> None:
            raise AssertionError(f"unexpected update task: {task!r}")

    monkeypatch.setattr(tray_mod.updater, "check_for_update", fake_check_for_update)
    tray._pool = FailingPool()

    tray._maybe_check_for_updates_on_startup()

    assert calls == 0


def test_startup_auto_check_runs_when_enabled(qapp) -> None:
    cfg = RinConfig()
    cfg.auto_check_updates = True
    tray = _make_tray(qapp, cfg)
    enqueued: list[object] = []

    class FakePool:
        def start(self, task: object) -> None:
            enqueued.append(task)

    tray._pool = FakePool()

    tray._maybe_check_for_updates_on_startup()

    assert len(enqueued) == 1


def test_update_check_completed_with_new_version_calls_notify(qapp, monkeypatch) -> None:
    from rin.ui import tray as tray_mod

    tray = _make_tray(qapp)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_notify(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(tray_mod, "notify", fake_notify)
    info = UpdateInfo(
        latest="9.9.9",
        html_url="https://example.com/releases/tag/v9.9.9",
        asset_url=None,
        asset_size_mb=12.4,
        published_at=None,
    )

    tray._on_update_check_completed(info, was_manual=True)

    assert calls
    assert "9.9.9" in str(calls[0][0][0])
    assert tray._pending_update_url == info.html_url


def test_update_check_completed_none_silent_on_startup(qapp, monkeypatch) -> None:
    from rin.ui import tray as tray_mod

    tray = _make_tray(qapp)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_notify(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(tray_mod, "notify", fake_notify)

    tray._on_update_check_completed(None, was_manual=False)

    assert calls == []


def test_update_check_completed_none_speaks_on_manual(qapp, monkeypatch) -> None:
    from rin.ui import tray as tray_mod

    tray = _make_tray(qapp)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_notify(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(tray_mod, "notify", fake_notify)

    tray._on_update_check_completed(None, was_manual=True)

    assert calls
    message = " ".join(str(arg) for arg in calls[0][0]).lower()
    assert "up to date" in message or "latest" in message

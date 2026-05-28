"""Tests for the Settings -> Privacy pause controls (moved from tray in v0.7.1)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rin.config import RinConfig


def test_pause_check_round_trips_through_config(qapp) -> None:
    from rin.ui.settings_dialog import SettingsDialog

    cfg = RinConfig()
    cfg.paused = True
    dlg = SettingsDialog(cfg)
    dlg.load_from_config()
    assert dlg._privacy_pause_check.isChecked() is True

    dlg._privacy_pause_check.setChecked(False)
    dlg._on_save()
    assert cfg.paused is False


def test_pause_check_default_unpaused(qapp) -> None:
    from rin.ui.settings_dialog import SettingsDialog

    cfg = RinConfig()
    dlg = SettingsDialog(cfg)
    dlg.load_from_config()
    assert dlg._privacy_pause_check.isChecked() is False


def test_apply_timed_pause_writes_paused_until_iso(
    qapp, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    from rin import paths as paths_mod
    paths_mod.reset_cache()

    from rin.ui.settings_dialog import SettingsDialog

    cfg = RinConfig()
    dlg = SettingsDialog(cfg)
    dlg.load_from_config()

    dlg._apply_timed_pause(minutes=15)
    assert cfg.privacy.paused_until_iso is not None
    until = datetime.fromisoformat(cfg.privacy.paused_until_iso)
    delta = until - datetime.now()
    # ~15 min ahead; allow generous slack for slow CI
    assert timedelta(minutes=14) < delta < timedelta(minutes=16)
    # Status label reflects the change
    assert "Paused until" in dlg._privacy_timed_status.text()
    assert dlg._privacy_resume_btn.isEnabled() is True

    paths_mod.reset_cache()


def test_clear_timed_pause_resets_iso_and_button_state(
    qapp, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    from rin import paths as paths_mod
    paths_mod.reset_cache()

    from rin.ui.settings_dialog import SettingsDialog

    cfg = RinConfig()
    cfg.privacy.paused_until_iso = (
        datetime.now() + timedelta(minutes=30)
    ).isoformat()
    dlg = SettingsDialog(cfg)
    dlg.load_from_config()
    # Label shows pause active
    assert "Paused until" in dlg._privacy_timed_status.text()

    dlg._clear_timed_pause()
    assert cfg.privacy.paused_until_iso is None
    assert dlg._privacy_timed_status.text() == "Not paused"
    assert dlg._privacy_resume_btn.isEnabled() is False

    paths_mod.reset_cache()


def test_expired_pause_treated_as_not_paused(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    from rin import paths as paths_mod
    paths_mod.reset_cache()

    from rin.ui.settings_dialog import SettingsDialog

    cfg = RinConfig()
    # An ISO that has already elapsed
    cfg.privacy.paused_until_iso = (
        datetime.now() - timedelta(minutes=5)
    ).isoformat()
    dlg = SettingsDialog(cfg)
    dlg.load_from_config()
    assert dlg._privacy_timed_status.text() == "Not paused"
    assert dlg._privacy_resume_btn.isEnabled() is False

    paths_mod.reset_cache()


def test_tray_menu_no_longer_has_pause_entries(qapp) -> None:
    """Pause entries were moved from the tray menu to Settings in v0.7.1."""

    # Avoid the privacy attribute defaults that pull live machine state
    from rin.ui.tray import TrayApp

    cfg = RinConfig()
    tray = TrayApp(cfg)
    labels = [a.text() for a in tray._menu.actions() if not a.isSeparator()]
    # No more pause menu items
    assert not any("Pause captures" in lbl for lbl in labels), labels
    assert not any("Pause captures for" in lbl for lbl in labels), labels


def test_tray_panic_toggle_still_works_without_pause_menu(qapp) -> None:
    """Ctrl+Alt+Shift+P remains a runtime toggle (no longer touches the menu)."""

    from rin.ui.tray import TrayApp

    cfg = RinConfig()
    tray = TrayApp(cfg)
    assert tray.input_manager.is_paused() is False
    tray._panic_toggle()
    assert tray.input_manager.is_paused() is True
    tray._panic_toggle()
    assert tray.input_manager.is_paused() is False


@pytest.fixture()
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    from rin import paths as paths_mod
    paths_mod.reset_cache()
    yield tmp_path
    paths_mod.reset_cache()

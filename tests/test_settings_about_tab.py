"""Settings -> About tab tests."""
from __future__ import annotations

import pytest

import rin
from rin.config import RinConfig
from rin.utils.updater import UpdateInfo


@pytest.fixture()
def settings_dialog_module(monkeypatch: pytest.MonkeyPatch):
    from rin.ui import settings_dialog

    monkeypatch.setattr(
        settings_dialog.SettingsDialog,
        "_refresh_audio_devices",
        lambda self: None,
    )
    return settings_dialog


def test_about_tab_shows_current_version(qapp, settings_dialog_module) -> None:
    dlg = settings_dialog_module.SettingsDialog(RinConfig())

    assert dlg._about_version_chip.text() == f"v{rin.__version__}"


def test_auto_check_updates_checkbox_reflects_config_default(
    qapp,
    settings_dialog_module,
) -> None:
    dlg = settings_dialog_module.SettingsDialog(RinConfig())

    assert dlg._auto_check_updates_check.isChecked() is True


def test_auto_check_updates_checkbox_round_trip(qapp, settings_dialog_module) -> None:
    dlg = settings_dialog_module.SettingsDialog(RinConfig())

    dlg._auto_check_updates_check.setChecked(False)
    dlg._on_save()

    reloaded = RinConfig.load()
    assert reloaded.auto_check_updates is False


def test_check_for_updates_button_disables_during_check(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
    settings_dialog_module,
) -> None:
    dlg = settings_dialog_module.SettingsDialog(RinConfig())
    started = []

    class FakePool:
        def start(self, worker) -> None:
            started.append(worker)

    class FakeThreadPool:
        @staticmethod
        def globalInstance() -> FakePool:
            return FakePool()

    monkeypatch.setattr(settings_dialog_module, "QThreadPool", FakeThreadPool)

    dlg._check_updates_btn.click()

    assert started
    assert dlg._check_updates_btn.isEnabled() is False


def test_on_check_updates_finished_none_shows_up_to_date(
    qapp,
    settings_dialog_module,
) -> None:
    dlg = settings_dialog_module.SettingsDialog(RinConfig())
    dlg._nav.setCurrentRow(dlg._nav.count() - 1)
    dlg.show()
    qapp.processEvents()

    dlg._on_check_updates_finished(None)

    status = dlg._check_updates_status.text().lower()
    assert "latest" in status or "up to date" in status
    assert dlg._release_link.isVisible() is False


def test_on_check_updates_finished_with_info_shows_link(
    qapp,
    settings_dialog_module,
) -> None:
    dlg = settings_dialog_module.SettingsDialog(RinConfig())
    dlg._nav.setCurrentRow(dlg._nav.count() - 1)
    dlg.show()
    qapp.processEvents()
    info = UpdateInfo(
        latest="0.9.0",
        html_url="https://example.com/r",
        asset_url=None,
        asset_size_mb=429.2,
        published_at=None,
    )

    dlg._on_check_updates_finished(info)

    assert "0.9.0" in dlg._check_updates_status.text()
    assert dlg._release_link.isVisible() is True
    assert "https://example.com/r" in dlg._release_link.text()

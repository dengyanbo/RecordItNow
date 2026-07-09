"""Settings dialog round-trip tests."""
from __future__ import annotations

from rin.config import RinConfig, TriggerBinding
from rin.ui.settings_dialog import SettingsDialog


def test_dialog_loads_values_from_config(qapp) -> None:
    cfg = RinConfig()
    cfg.trigger = TriggerBinding(
        source="keyboard", key="F12", hold_threshold_ms=750, label="Key: F12"
    )
    cfg.working_hours.start_hour = 8
    cfg.working_hours.end_hour = 19
    cfg.working_hours.weekdays = [0, 2, 4]
    cfg.llm.name = "openai"
    cfg.llm.model = "gpt-4o"
    cfg.storage.raw_retention_days = 14

    dlg = SettingsDialog(cfg)
    assert dlg._hold_spin.value() == 750
    assert dlg._wh_start.value() == 8
    assert dlg._wh_end.value() == 19
    assert [i for i, cb in enumerate(dlg._weekday_checks) if cb.isChecked()] == [0, 2, 4]
    assert dlg._llm_combo.currentText() == "openai"
    assert dlg._llm_model.currentText() == "gpt-4o"
    assert dlg._retention_spin.value() == 14
    assert "F12" in dlg._binding_label.text()


def test_dialog_save_round_trip(qapp) -> None:
    cfg = RinConfig()
    dlg = SettingsDialog(cfg)
    dlg._hold_spin.setValue(900)
    dlg._wh_start.setValue(7)
    dlg._wh_end.setValue(20)
    dlg._llm_combo.setCurrentText("azure")
    dlg._azure_endpoint.setText("https://contoso.openai.azure.com")
    dlg._azure_deployment.setText("dep1")
    dlg._retention_spin.setValue(45)
    dlg._keep_summaries.setChecked(False)

    dlg._on_save()

    reloaded = RinConfig.load()
    assert reloaded.trigger.hold_threshold_ms == 900
    assert reloaded.working_hours.start_hour == 7
    assert reloaded.working_hours.end_hour == 20
    assert reloaded.llm.name == "azure"
    assert reloaded.llm.azure_endpoint == "https://contoso.openai.azure.com"
    assert reloaded.llm.azure_deployment == "dep1"
    assert reloaded.storage.raw_retention_days == 45
    assert reloaded.storage.keep_summaries_forever is False


def test_learn_callback_is_invoked(qapp) -> None:
    cfg = RinConfig()
    captured: list = []

    def fake_learn(on_captured):
        captured.append(on_captured)
        on_captured(TriggerBinding(source="keyboard", key="F9", label="Key: F9"))

    dlg = SettingsDialog(cfg, learn_callback=fake_learn)
    dlg._on_learn_clicked()
    assert len(captured) == 1
    assert dlg._config.trigger.key == "F9"
    assert "F9" in dlg._binding_label.text()

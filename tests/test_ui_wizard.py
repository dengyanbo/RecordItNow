"""Tests for the first-run onboarding wizard."""
from __future__ import annotations

from rin.config import RinConfig, TriggerBinding
from rin.ui.wizard import FirstRunWizard


def test_wizard_constructs(qapp) -> None:
    wizard = FirstRunWizard(RinConfig())
    assert wizard.pageIds() == [0, 1, 2, 3, 4]
    assert wizard.windowTitle() == "Welcome to RIN"



def test_wizard_happy_path_sets_first_run_completed(qapp) -> None:
    cfg = RinConfig()
    wizard = FirstRunWizard(cfg)

    wizard._trigger_page._on_binding_learned(
        TriggerBinding(source="keyboard", key="F8", label="Key: F8")
    )
    wizard._provider_page._combo.setCurrentText("openai")
    wizard._hours_page._enabled.setChecked(False)
    wizard._hours_page._start.setValue(8)
    wizard._hours_page._end.setValue(17)

    wizard.accept()

    reloaded = RinConfig.load()
    assert cfg.first_run_completed is True
    assert reloaded.first_run_completed is True
    assert reloaded.trigger.key == "F8"
    assert reloaded.llm.name == "openai"
    assert reloaded.working_hours.enabled is False

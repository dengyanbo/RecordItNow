"""Copilot model default + deprecated-model self-heal tests.

The Copilot CLI model default is ``"auto"`` (Copilot picks its best current
model), and configs still pinned to a retired model heal to ``"auto"`` on
load so analysis never breaks on a deprecated model.
"""
from __future__ import annotations

import tomllib

from rin.config import RinConfig


def test_default_copilot_model_is_auto() -> None:
    assert RinConfig().llm.model == "auto"


def test_deprecated_model_heals_to_auto_on_load(tmp_path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg = RinConfig()
    cfg.llm.name = "copilot_cli"
    cfg.llm.model = "claude-opus-4.7-1m-internal"  # retired
    cfg.save(cfg_path)

    loaded = RinConfig.load(cfg_path)
    assert loaded.llm.model == "auto"

    # The heal is persisted so it only happens once.
    with cfg_path.open("rb") as fh:
        assert tomllib.load(fh)["llm"]["model"] == "auto"


def test_user_chosen_model_is_left_untouched(tmp_path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg = RinConfig()
    cfg.llm.model = "gpt-5.4"
    cfg.save(cfg_path)

    assert RinConfig.load(cfg_path).llm.model == "gpt-5.4"


def test_empty_model_is_left_untouched(tmp_path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg = RinConfig()
    cfg.llm.model = ""  # explicit "provider default"
    cfg.save(cfg_path)

    assert RinConfig.load(cfg_path).llm.model == ""


def test_deprecated_string_not_healed_for_non_copilot(tmp_path) -> None:
    # The heal only applies to the copilot_cli provider.
    cfg_path = tmp_path / "config.toml"
    cfg = RinConfig()
    cfg.llm.name = "openai"
    cfg.llm.model = "claude-opus-4.7-1m-internal"
    cfg.save(cfg_path)

    assert RinConfig.load(cfg_path).llm.model == "claude-opus-4.7-1m-internal"

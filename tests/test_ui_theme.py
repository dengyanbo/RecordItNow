"""Tests for the Fluent-inspired design system (theme.py + style.py)."""
from __future__ import annotations

import pytest

from rin.config import RinConfig
from rin.ui.style import palette_to_qss
from rin.ui.theme import (
    ACCENTS,
    DARK,
    LIGHT,
    contrast_ratio,
    relative_luminance,
    resolve,
    with_accent,
)


def test_both_presets_define_every_token() -> None:
    for theme in (LIGHT, DARK):
        # Every field must be set (non-empty hex or a sane int).
        for field in (
            "bg", "surface", "surface_alt", "border", "text", "text_muted",
            "text_disabled", "accent", "accent_hover", "accent_pressed",
            "on_accent", "success", "warning", "danger", "selection_bg",
        ):
            val = getattr(theme, field)
            assert isinstance(val, str)
            assert val.startswith("#") and len(val) == 7, f"{theme.name}.{field} = {val!r}"


def test_resolve_modes() -> None:
    assert resolve("light").name == "light"
    assert resolve("dark").name == "dark"
    # "auto" picks whichever based on the host registry — accept either.
    auto = resolve("auto")
    assert auto.name in {"light", "dark"}


def test_with_accent_changes_accent_color() -> None:
    base = LIGHT
    purple = with_accent(base, "purple")
    assert purple.accent == ACCENTS["purple"]["light"]
    assert purple.accent != base.accent
    # Unknown accent name → return theme unchanged.
    assert with_accent(base, "neon").accent == base.accent


def test_wcag_aa_contrast_for_text_on_bg() -> None:
    """Body text on the main background must clear WCAG AA (4.5:1)."""

    for theme in (LIGHT, DARK):
        ratio = contrast_ratio(theme.text, theme.bg)
        assert ratio >= 4.5, f"{theme.name}: text/bg contrast={ratio:.2f}"


def test_wcag_aa_contrast_for_on_accent() -> None:
    """``on_accent`` text must be readable on every accent variant."""

    for theme in (LIGHT, DARK):
        for name in ACCENTS:
            tweaked = with_accent(theme, name)
            ratio = contrast_ratio(tweaked.on_accent, tweaked.accent)
            # 3.0 is large-text AA; primary buttons use bold ≥10pt so this is OK.
            assert ratio >= 3.0, f"{theme.name}/{name}: on_accent/accent={ratio:.2f}"


def test_relative_luminance_known_values() -> None:
    assert relative_luminance("#000000") == pytest.approx(0.0)
    assert relative_luminance("#FFFFFF") == pytest.approx(1.0, abs=1e-6)


def test_palette_to_qss_non_empty_and_well_formed() -> None:
    qss = palette_to_qss(LIGHT)
    assert len(qss) > 1000
    # Spot-check a few selectors we rely on.
    for selector in ("QWidget", "QPushButton", "QListWidget", "QMenu",
                     "QScrollBar", "QToolTip", "QLineEdit"):
        assert selector in qss
    # And the active accent color must appear.
    assert LIGHT.accent in qss


def test_palette_to_qss_density_affects_padding() -> None:
    comfortable = palette_to_qss(LIGHT, density="comfortable")
    compact = palette_to_qss(LIGHT, density="compact")
    assert comfortable != compact
    # comfortable padding > compact padding → comfortable string sees the larger pixel value.
    assert "10px" in comfortable
    assert "6px" in compact


def test_default_config_includes_ui_section() -> None:
    cfg = RinConfig()
    assert cfg.ui.theme == "auto"
    assert cfg.ui.accent == "blue"
    assert cfg.ui.density == "comfortable"

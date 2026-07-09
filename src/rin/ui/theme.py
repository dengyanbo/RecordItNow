"""Design tokens for RIN's modern Fluent-inspired UI.

A single :class:`Theme` dataclass holds every color RIN's stylesheet
needs. Two presets (``LIGHT`` and ``DARK``) ship by default, and
:func:`system_theme` delegates OS detection through
:mod:`rin.utils.platform_compat`.

The brand color (accent) is Microsoft-blue (``#0078D4`` on light,
``#60CDFF`` on dark) by default. Other presets in :data:`ACCENTS` allow
the user to pick purple / teal / orange in the Appearance settings tab.

All color values are hex strings ``#rrggbb`` for easy interpolation in
Qt's QSS engine.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from ..utils import platform_compat

ThemeName = Literal["light", "dark"]
ThemeMode = Literal["light", "dark", "auto"]
Density = Literal["compact", "comfortable"]


@dataclass(frozen=True)
class Theme:
    """A complete color palette + a handful of layout tokens.

    Tokens follow Fluent 2 specs:
      - Body 14px / Caption 12px / Subtitle 16px Semibold / Title 1 28px Semibold
      - 4 / 8 / 12 / 16 / 24 px spacing grid
      - Button corner radius 4 px, card 8 px
      - Standard control height 32 px
    """

    name: ThemeName

    # backgrounds
    bg: str            # main window
    surface: str       # cards, dialogs
    surface_alt: str   # input fields, hover state
    surface_hover: str # subtle hover on list rows
    surface_card: str  # raised card background (slightly different from surface)
    border: str        # 1 px outlines
    border_strong: str # dividers + selected outlines

    # text
    text: str          # primary text
    text_muted: str    # secondary text, hints
    text_disabled: str

    # brand + state
    accent: str        # primary action color
    accent_hover: str  # hover on accent
    accent_pressed: str
    accent_subtle: str # tinted fill behind accent text (selected nav, user bubble)
    on_accent: str     # text/icon color drawn on accent fills

    success: str
    warning: str
    danger: str

    # widgets
    selection_bg: str  # list row selection
    scrollbar: str
    scrollbar_hover: str
    focus_ring: str    # 2 px focus outline color (mostly accent w/ alpha)

    # layout — Fluent 2 ramp
    radius_button: int = 4
    radius_card: int = 8
    radius_window: int = 8
    radius_chip: int = 12

    # type ramp (point-size for Qt, roughly Fluent 2 pixel values @ 96 DPI)
    # Title 1 / Subtitle / Body / Caption — Fluent 2 typographic ramp.
    font_size_caption: int = 9       # 12 px
    font_size_body: int = 10         # 14 px
    font_size_body_strong: int = 10  # 14 px Semibold (same size, different weight)
    font_size_subtitle: int = 12     # 16 px Semibold
    font_size_title: int = 16        # 22 px Semibold — section heading (h1 on page)
    font_size_display: int = 22      # 28 px Semibold — window/page hero heading

    # spacing — Fluent 2 grid
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24

    # density-aware padding (used by style.py)
    padding_compact: int = 6
    padding_comfortable: int = 8

    # font families — Windows 11 ships the variable family. Older Win 10 falls back.
    font_family: str = "'Segoe UI Variable', 'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif"
    font_family_display: str = (
        "'Segoe UI Variable Display', 'Segoe UI Variable', 'Segoe UI Semibold', "
        "'Segoe UI', Arial, sans-serif"
    )

    # backwards-compat alias (old code reads ``.font_size_pt``)
    @property
    def font_size_pt(self) -> int:
        return self.font_size_body


LIGHT = Theme(
    name="light",
    bg="#F3F3F3",
    surface="#FFFFFF",
    surface_alt="#FAFAFA",
    surface_hover="#F0F0F0",
    surface_card="#FFFFFF",
    border="#D6D6D6",
    border_strong="#B5B5B5",
    text="#1F1F1F",
    text_muted="#616161",
    text_disabled="#A0A0A0",
    accent="#0078D4",
    accent_hover="#106EBE",
    accent_pressed="#005A9E",
    accent_subtle="#E5F1FB",
    on_accent="#FFFFFF",
    success="#107C10",
    warning="#C19C00",
    danger="#C42B1C",
    selection_bg="#CCE4F7",
    scrollbar="#C8C8C8",
    scrollbar_hover="#A0A0A0",
    focus_ring="#0078D4",
)


DARK = Theme(
    name="dark",
    bg="#202020",
    surface="#2B2B2B",
    surface_alt="#323232",
    surface_hover="#3A3A3A",
    surface_card="#2D2D2D",
    border="#484848",
    border_strong="#5A5A5A",
    text="#F5F5F5",
    text_muted="#C7C7C7",
    text_disabled="#6C6C6C",
    accent="#60CDFF",
    accent_hover="#4FB8E8",
    accent_pressed="#3DA1CC",
    accent_subtle="#1B3D52",
    on_accent="#000000",
    success="#6CCB5F",
    warning="#FCE100",
    danger="#FF99A4",
    selection_bg="#163E5C",
    scrollbar="#5A5A5A",
    scrollbar_hover="#7A7A7A",
    focus_ring="#60CDFF",
)


ACCENTS: dict[str, dict[ThemeName, str]] = {
    "blue":   {"light": "#0078D4", "dark": "#60CDFF"},
    "purple": {"light": "#744DA9", "dark": "#B4A0FF"},
    # Light/teal at #00B7C3 fails WCAG AA (2.45:1 vs white). Darkened to
    # ~#017E87 → ratio ≈ 5.0:1 while still reading clearly as "teal".
    "teal":   {"light": "#017E87", "dark": "#5DE5EA"},
    "orange": {"light": "#CA5010", "dark": "#FCB97F"},
}


def system_theme() -> ThemeName:
    """Return the current system theme preference.

    Windows reads the registry; the current macOS/Linux scaffolding returns
    ``"light"`` until those backends grow real implementations.
    """

    return platform_compat.get_system_theme()


def resolve(mode: ThemeMode) -> Theme:
    """Return the active :class:`Theme` for ``mode``.

    * ``"light"`` / ``"dark"`` → return the corresponding fixed theme.
    * ``"auto"`` → pick based on the current system preference.
    """

    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    return LIGHT if system_theme() == "light" else DARK


def with_accent(theme: Theme, accent_name: str) -> Theme:
    """Return a copy of ``theme`` with the named accent color applied."""

    if accent_name not in ACCENTS:
        return theme
    accent = ACCENTS[accent_name][theme.name]
    # accent_subtle is the accent colour mixed with the bg so it reads as a
    # gentle tint behind selected nav rows / user chat bubbles. We can't
    # rely on QSS alpha (it doesn't render correctly behind a parent that
    # already has a colour), so pre-compute a flat blend.
    mix = 0.86 if theme.name == "light" else 0.78
    subtle = _mix(accent, theme.bg, mix)
    return replace(
        theme,
        accent=accent,
        accent_hover=_shade(accent, -0.10),
        accent_pressed=_shade(accent, -0.20),
        accent_subtle=subtle,
        focus_ring=accent,
    )


def current_theme(config: Any) -> Theme:
    """Resolve the active accented :class:`Theme` for a ``RinConfig``.

    Convenience wrapper for the ``with_accent(resolve(cfg.ui.theme),
    cfg.ui.accent)`` pattern used across every UI surface. ``config`` is any
    object exposing ``.ui.theme`` and ``.ui.accent`` (a :class:`RinConfig`).
    """

    ui = config.ui
    return with_accent(resolve(ui.theme), ui.accent)


def _mix(fg: str, bg: str, bg_amount: float) -> str:
    """Linear blend of two ``#rrggbb`` colors. ``bg_amount`` 0..1."""

    fg_hex, bg_hex = fg.lstrip("#"), bg.lstrip("#")
    fr, fg_, fb = (int(fg_hex[i : i + 2], 16) for i in (0, 2, 4))
    br, bg_g, bb = (int(bg_hex[i : i + 2], 16) for i in (0, 2, 4))
    a = max(0.0, min(1.0, bg_amount))
    r = int(fr * (1 - a) + br * a)
    g = int(fg_ * (1 - a) + bg_g * a)
    b = int(fb * (1 - a) + bb * a)
    return f"#{r:02X}{g:02X}{b:02X}"


def _shade(hex_color: str, amount: float) -> str:
    """Lighten (positive amount) or darken (negative) an ``#rrggbb`` color."""

    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    if amount >= 0:
        r = int(r + (255 - r) * amount)
        g = int(g + (255 - g) * amount)
        b = int(b + (255 - b) * amount)
    else:
        r = int(r * (1 + amount))
        g = int(g * (1 + amount))
        b = int(b * (1 + amount))
    return f"#{r:02X}{g:02X}{b:02X}"


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance for a color (used by the contrast tests)."""

    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two colors. Higher is more readable."""

    lf, lb = relative_luminance(fg), relative_luminance(bg)
    light, dark = max(lf, lb), min(lf, lb)
    return (light + 0.05) / (dark + 0.05)


__all__ = [
    "ACCENTS",
    "DARK",
    "Density",
    "LIGHT",
    "Theme",
    "ThemeMode",
    "ThemeName",
    "contrast_ratio",
    "current_theme",
    "relative_luminance",
    "resolve",
    "system_theme",
    "with_accent",
]

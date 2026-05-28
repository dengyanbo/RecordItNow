"""Render a complete Qt stylesheet from a :class:`~rin.ui.theme.Theme`.

We don't use Qt resource compilation (rcc) — the QSS is a single Python
f-string filled in from the active theme. This makes live theme swaps a
one-line ``QApplication.setStyleSheet(palette_to_qss(new_theme))``.

The stylesheet covers every widget RIN actually uses (`grep -r 'Q[A-Z]'`
on `src/rin/ui/`):

* QWidget (base font + colors)
* QPushButton (default + primary + flat)
* QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser
* QCheckBox, QRadioButton
* QTabWidget, QTabBar
* QListWidget, QListView
* QMenu, QMenuBar
* QDialog, QFrame#card
* QScrollBar
* QSystemTrayIcon — not stylable via QSS; handled at the icon factory layer
"""
from __future__ import annotations

from .theme import Density, Theme


def palette_to_qss(theme: Theme, *, density: Density = "comfortable") -> str:
    """Return a full Qt stylesheet string for ``theme`` and ``density``."""

    t = theme
    pad_y = t.padding_compact if density == "compact" else t.padding_comfortable
    pad_x = pad_y + 4
    return f"""
/* === RIN modern Fluent stylesheet (Fluent 2 calibrated, v0.4.1 polish) === */

* {{
    outline: none;
}}

QWidget {{
    background-color: {t.bg};
    color: {t.text};
    font-family: {t.font_family};
    font-size: {t.font_size_body}pt;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

QDialog,
QMainWindow {{
    background-color: {t.bg};
}}

QFrame#card,
QWidget#card {{
    background-color: {t.surface_card};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
}}

/* ----- typography ------------------------------------------------------ */

QLabel {{
    background: transparent;
    color: {t.text};
}}

QLabel[muted="true"],
QLabel[role="caption"] {{
    color: {t.text_muted};
    font-size: {t.font_size_caption}pt;
}}

QLabel[role="field-label"] {{
    color: {t.text};
    font-size: {t.font_size_caption}pt;
    font-weight: 600;
    padding: 0 0 4px 0;
    letter-spacing: 0.2px;
}}

QLabel[role="field-hint"] {{
    color: {t.text_muted};
    font-size: {t.font_size_caption}pt;
    padding: 2px 0 0 0;
}}

QLabel[heading="hero"] {{
    font-family: {t.font_family_display};
    font-size: {t.font_size_display}pt;
    font-weight: 600;
    color: {t.text};
    letter-spacing: -0.2px;
}}

QLabel[heading="h1"] {{
    font-family: {t.font_family_display};
    font-size: {t.font_size_title}pt;
    font-weight: 600;
    color: {t.text};
    letter-spacing: -0.1px;
}}

QLabel[heading="h2"] {{
    font-size: {t.font_size_subtitle}pt;
    font-weight: 600;
    color: {t.text};
}}

QLabel[heading="subtle"] {{
    font-size: {t.font_size_caption}pt;
    font-weight: 600;
    color: {t.text_muted};
    letter-spacing: 0.4px;
    text-transform: uppercase;
}}

QLabel[role="empty-state-title"] {{
    color: {t.text};
    font-size: {t.font_size_subtitle}pt;
    font-weight: 600;
}}

QLabel[role="empty-state-hint"] {{
    color: {t.text_muted};
    font-size: {t.font_size_body}pt;
}}

QLabel[role="chip"] {{
    background-color: {t.surface_alt};
    color: {t.text_muted};
    border: 1px solid {t.border};
    border-radius: {t.radius_chip}px;
    padding: 1px 8px;
    font-size: {t.font_size_caption}pt;
    font-weight: 600;
}}

QLabel[role="chip"][accent="true"] {{
    background-color: {t.accent_subtle};
    color: {t.accent_pressed};
    border-color: {t.accent_subtle};
}}

/* ----- buttons --------------------------------------------------------- */

QPushButton {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_button}px;
    padding: 0 {pad_x + 4}px;
    min-height: 30px;
    max-height: 32px;
    min-width: 84px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {t.surface_hover};
    border-color: {t.text_muted};
}}

QPushButton:pressed {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
}}

QPushButton:focus {{
    border: 2px solid {t.focus_ring};
    padding: 0 {pad_x + 3}px;
}}

QPushButton:disabled {{
    color: {t.text_disabled};
    border-color: {t.border};
    background-color: {t.surface};
}}

QPushButton[primary="true"] {{
    background-color: {t.accent};
    color: {t.on_accent};
    border: 1px solid {t.accent};
    font-weight: 600;
}}

QPushButton[primary="true"]:hover {{
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
}}

QPushButton[primary="true"]:pressed {{
    background-color: {t.accent_pressed};
    border-color: {t.accent_pressed};
}}

QPushButton[primary="true"]:focus {{
    border: 2px solid {t.on_accent};
    padding: 0 {pad_x + 3}px;
}}

QPushButton[flat="true"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t.accent};
    padding: 4px {pad_x}px;
    min-height: 26px;
    min-width: 0;
    font-weight: 500;
}}

QPushButton[flat="true"]:hover {{
    background-color: {t.accent_subtle};
    color: {t.accent_pressed};
}}

QPushButton[flat="true"]:focus {{
    border-color: {t.focus_ring};
}}

QPushButton[role="icon"] {{
    background: transparent;
    border: 1px solid transparent;
    padding: 4px;
    min-width: 28px;
    max-width: 32px;
    min-height: 28px;
    max-height: 32px;
}}

QPushButton[role="icon"]:hover {{
    background-color: {t.surface_hover};
    border-color: {t.border};
}}

QPushButton[role="icon"]:focus {{
    border-color: {t.focus_ring};
}}

/* ----- inputs ---------------------------------------------------------- */

QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox,
QPlainTextEdit,
QTextEdit,
QTextBrowser {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_button}px;
    padding: 0 {pad_x}px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {{
    min-height: 30px;
    max-height: 32px;
}}

QLineEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QComboBox:hover {{
    border-color: {t.text_muted};
}}

QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QTextBrowser:focus {{
    border: 2px solid {t.focus_ring};
    padding: 0 {pad_x - 1}px;
}}

QLineEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled,
QComboBox:disabled {{
    color: {t.text_disabled};
    border-color: {t.border};
    background-color: {t.surface_alt};
}}

QSpinBox::up-button,
QSpinBox::down-button,
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {{
    border: none;
    background: transparent;
    width: 18px;
}}

QSpinBox::up-button:hover,
QSpinBox::down-button:hover {{
    background: {t.surface_hover};
}}

QComboBox::drop-down {{
    border: none;
    background: transparent;
    width: 22px;
    padding-right: 4px;
}}

QComboBox::down-arrow {{
    image: none;
    width: 0;
}}

QComboBox QAbstractItemView {{
    background-color: {t.surface};
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_button}px;
    color: {t.text};
    selection-background-color: {t.accent_subtle};
    selection-color: {t.text};
    padding: 4px;
    outline: none;
}}

/* ----- toggles --------------------------------------------------------- */

QCheckBox,
QRadioButton {{
    background: transparent;
    color: {t.text};
    spacing: 8px;
    padding: 2px;
}}

QCheckBox::indicator,
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1.5px solid {t.text_muted};
    background: {t.surface};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator:hover,
QRadioButton::indicator:hover {{
    border-color: {t.accent};
}}

QCheckBox::indicator:checked,
QRadioButton::indicator:checked {{
    background-color: {t.accent};
    border-color: {t.accent};
}}

QCheckBox:focus,
QRadioButton:focus {{
    color: {t.text};
}}

/* ----- tabs ------------------------------------------------------------ */

QTabWidget::pane {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {t.text_muted};
    padding: 6px {pad_x + 4}px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-weight: 500;
}}

QTabBar::tab:hover {{
    color: {t.text};
}}

QTabBar::tab:selected {{
    color: {t.text};
    border-bottom-color: {t.accent};
    font-weight: 600;
}}

/* ----- lists ----------------------------------------------------------- */

QListWidget,
QListView,
QTreeView {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    color: {t.text};
    outline: none;
    padding: 4px;
}}

QListWidget::item,
QListView::item {{
    padding: 6px {pad_x}px;
    border-radius: {t.radius_button}px;
    border: none;
}}

QListWidget::item:hover,
QListView::item:hover {{
    background-color: {t.surface_hover};
}}

QListWidget::item:selected,
QListView::item:selected {{
    background-color: {t.accent_subtle};
    color: {t.text};
}}

/* a special pill-style left nav, e.g. for the Settings dialog */

QListWidget[role="nav"] {{
    background: {t.bg};
    border: none;
    border-right: 1px solid {t.border};
    border-radius: 0;
    padding: 12px 8px;
}}

QListWidget[role="nav"]::item {{
    color: {t.text_muted};
    padding: 8px 10px 8px 14px;
    border-radius: {t.radius_button}px;
    border-left: 3px solid transparent;
    margin: 1px 0;
    min-height: 30px;
    font-weight: 500;
}}

QListWidget[role="nav"]::item:hover {{
    background-color: {t.surface_hover};
    color: {t.text};
}}

QListWidget[role="nav"]::item:selected {{
    background-color: {t.accent_subtle};
    color: {t.text};
    border-left: 3px solid {t.accent};
    font-weight: 600;
}}

/* sections grouped without a chrome'd card — used by Reports list */

QListWidget[role="cards"] {{
    background: transparent;
    border: none;
    padding: 0;
}}

QListWidget[role="cards"]::item {{
    background: {t.surface_card};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    padding: 0;
    margin-bottom: 8px;
}}

QListWidget[role="cards"]::item:hover {{
    background: {t.surface_hover};
    border-color: {t.border_strong};
}}

QListWidget[role="cards"]::item:selected {{
    border-color: {t.accent};
    background: {t.accent_subtle};
}}

/* ----- menus ----------------------------------------------------------- */

QMenu {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    padding: 6px;
    color: {t.text};
}}

QMenu::item {{
    padding: 6px {pad_x + 10}px;
    border-radius: {t.radius_button}px;
    margin: 1px 0;
    min-height: 24px;
}}

QMenu::item:selected {{
    background-color: {t.accent_subtle};
    color: {t.text};
}}

QMenu::item:disabled {{
    color: {t.text_disabled};
}}

QMenu::separator {{
    height: 1px;
    background: {t.border};
    margin: 6px 8px;
}}

/* ----- scrollbars ------------------------------------------------------ */

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 4px 2px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px 4px;
}}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {{
    background: {t.scrollbar};
    border-radius: 4px;
    min-height: 36px;
    min-width: 36px;
}}

QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{
    background: {t.scrollbar_hover};
}}

QScrollBar::add-line,
QScrollBar::sub-line,
QScrollBar::add-page,
QScrollBar::sub-page {{
    background: transparent;
    border: none;
    height: 0;
    width: 0;
}}

/* ----- footers / dividers --------------------------------------------- */

QFrame[role="divider"] {{
    background: {t.border};
    max-height: 1px;
    min-height: 1px;
    margin: 0;
    padding: 0;
    border: none;
}}

QFrame[role="divider-vert"] {{
    background: {t.border};
    max-width: 1px;
    min-width: 1px;
    margin: 0;
    padding: 0;
    border: none;
}}

QWidget#footer {{
    background: {t.surface};
    border-top: 1px solid {t.border};
}}

/* ----- chat bubbles ---------------------------------------------------- */

QFrame[role="user-bubble"] {{
    background-color: {t.accent_subtle};
    border: 1px solid {t.accent_subtle};
    border-radius: 12px;
    border-bottom-right-radius: 2px;
}}

QFrame[role="agent-bubble"] {{
    background-color: {t.surface_card};
    border: 1px solid {t.border};
    border-radius: 12px;
    border-bottom-left-radius: 2px;
}}

/* ----- combined search bar (line edit + attached button) -------------- */

QLineEdit[role="search"] {{
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}}

QPushButton[role="search-attached"] {{
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-left: 0;
    min-width: 96px;
}}

/* ----- group + frame --------------------------------------------------- */

QGroupBox {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    margin-top: 14px;
    padding: 10px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {t.text};
    font-weight: 600;
}}

QFrame[shape="HLine"],
QFrame[shape="VLine"] {{
    color: {t.border};
}}

QToolTip {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    padding: 6px 10px;
    border-radius: {t.radius_button}px;
}}
""".strip()

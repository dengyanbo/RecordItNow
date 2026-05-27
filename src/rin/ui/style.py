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
/* === RIN modern Fluent stylesheet (Fluent 2 calibrated) ============== */

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
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
}}

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
    color: {t.text_muted};
    font-size: {t.font_size_caption}pt;
    font-weight: 500;
    padding-bottom: 2px;
}}

QLabel[heading="h1"] {{
    font-size: {t.font_size_title}pt;
    font-weight: 600;
    color: {t.text};
}}

QLabel[heading="h2"] {{
    font-size: {t.font_size_subtitle}pt;
    font-weight: 600;
    color: {t.text};
}}

QLabel[role="empty-state-title"] {{
    color: {t.text_muted};
    font-size: {t.font_size_subtitle}pt;
    font-weight: 500;
}}

QLabel[role="empty-state-hint"] {{
    color: {t.text_muted};
    font-size: {t.font_size_body}pt;
}}

/* ----- buttons --------------------------------------------------------- */

QPushButton {{
    background-color: {t.surface_alt};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: {t.radius_button}px;
    padding: 0 {pad_x + 4}px;
    min-height: 30px;
    max-height: 32px;
}}

QPushButton:hover {{
    background-color: {t.surface_hover};
    border-color: {t.text_muted};
}}

QPushButton:pressed {{
    background-color: {t.border};
}}

QPushButton:disabled {{
    color: {t.text_disabled};
    border-color: {t.border};
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
}}

QPushButton[flat="true"] {{
    background: transparent;
    border: none;
    color: {t.accent};
    padding: 4px {pad_x}px;
    min-height: 24px;
}}

QPushButton[flat="true"]:hover {{
    background-color: {t.surface_hover};
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
    border: 1px solid {t.border};
    border-radius: {t.radius_button}px;
    padding: 0 {pad_x}px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {{
    min-height: 28px;
    max-height: 32px;
}}

QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QTextBrowser:focus {{
    border-color: {t.accent};
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
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
}}

QComboBox QAbstractItemView {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_button}px;
    color: {t.text};
    selection-background-color: {t.selection_bg};
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
    width: 16px;
    height: 16px;
    border: 1px solid {t.text_muted};
    background: {t.surface};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 8px;
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
    background-color: {t.selection_bg};
    color: {t.text};
}}

/* a special pill-style left nav, e.g. for the Settings dialog */

QListWidget[role="nav"] {{
    background: {t.surface_alt};
    border: none;
    border-right: 1px solid {t.border};
    border-radius: 0;
    padding: 8px 6px;
}}

QListWidget[role="nav"]::item {{
    color: {t.text_muted};
    padding: 8px 10px;
    border-radius: {t.radius_button}px;
    margin: 1px 0;
    min-height: 28px;
}}

QListWidget[role="nav"]::item:hover {{
    background-color: {t.surface_hover};
    color: {t.text};
}}

QListWidget[role="nav"]::item:selected {{
    background-color: {t.accent};
    color: {t.on_accent};
    font-weight: 600;
}}

/* sections grouped without a chrome'd card — used by Reports list */

QListWidget[role="cards"] {{
    background: transparent;
    border: none;
    padding: 0;
}}

QListWidget[role="cards"]::item {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    padding: 0;
    margin-bottom: 6px;
}}

QListWidget[role="cards"]::item:hover {{
    border-color: {t.accent_hover};
}}

QListWidget[role="cards"]::item:selected {{
    border-color: {t.accent};
    background: {t.surface_alt};
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
    padding: 6px {pad_x + 8}px;
    border-radius: {t.radius_button}px;
    margin: 1px 0;
    min-height: 22px;
}}

QMenu::item:selected {{
    background-color: {t.selection_bg};
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
    width: 10px;
    margin: 4px 2px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {{
    background: {t.scrollbar};
    border-radius: 3px;
    min-height: 30px;
    min-width: 30px;
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

QWidget#footer {{
    background: {t.bg};
    border-top: 1px solid {t.border};
}}

/* ----- group + frame --------------------------------------------------- */

QGroupBox {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
    margin-top: 12px;
    padding: 8px;
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
    border: 1px solid {t.border};
    padding: 6px 10px;
    border-radius: {t.radius_button}px;
}}
""".strip()

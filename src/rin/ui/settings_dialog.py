"""Settings dialog with a left-nav layout (v0.3.0 modern UI).

The dialog uses :class:`~rin.config.RinConfig` as the source of truth.
``load_from_config`` pulls fresh values; ``Save`` validates each field,
writes the updated values back into the in-memory config, persists the
TOML file, and emits ``config_saved`` so listeners (tray, input manager,
theme manager) can react.

Layout: a 220 px ``QListWidget`` on the left acts as a navigation rail
(``role="nav"`` for stylesheet pickup) with a 3 px accent stripe on the
selected row; the right pane is a ``QStackedWidget`` with one page per
section. Each page carries a hero heading + supporting caption, then a
form whose labels sit *above* their inputs with explicit field widths.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import RinConfig, TriggerBinding
from ..utils.logging import get_logger
from .progress import Spinner
from .theme import LIGHT, resolve, with_accent

log = get_logger(__name__)

LLM_NAMES = ["copilot_cli", "openai", "azure", "none"]
REPORT_FREQUENCIES = ["daily", "weekly", "off"]
REASONING_EFFORTS = ["", "none", "low", "medium", "high", "xhigh", "max"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
THEME_MODES = ["auto", "light", "dark"]
ACCENT_OPTIONS = ["blue", "purple", "teal", "orange"]
OCR_LANGUAGE_OPTIONS = [
    ("en", "English"),
    ("ch_sim", "Chinese (Simplified)"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
]
WHISPER_MODEL_OPTIONS = ["tiny", "base", "small", "medium", "large-v3"]
WHISPER_MODEL_HINTS = {
    "tiny": "Memory hint: fastest startup, ~1 GB RAM on CPU.",
    "base": "Memory hint: balanced for short notes, ~1.5 GB RAM on CPU.",
    "small": "Memory hint: recommended default, ~2 GB RAM on CPU.",
    "medium": "Memory hint: higher accuracy, ~5 GB RAM on CPU.",
    "large-v3": "Memory hint: best accuracy, expect ~10 GB RAM on CPU.",
}

# Standard input-width tiers — picked from Fluent 2 form patterns. Used
# everywhere instead of ``setMaximumWidth`` (which doesn't honor a
# QFormLayout's row).
_W_NUMBER = 132   # numeric input with suffix (e.g. "500 ms")
_W_PICKER = 220   # short combo / dropdown
_W_TEXT = 360     # free-form short text (model name)
_W_URL = 460      # URL / long text


def _nav_icon(name: str, color: str) -> QIcon:
    """Return a tinted Fluent SVG icon for the nav rail (theme-aware)."""

    try:
        from .icon import tinted_icon

        return tinted_icon(name, color)
    except Exception:
        return QIcon()


class SettingsDialog(QDialog):
    config_saved = Signal(RinConfig)

    # Each tab: (label, icon, supporting caption).
    NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
        ("Trigger",       "keyboard",  "What button captures or starts a recording."),
        ("Working hours", "clock",     "When background analysis is allowed to run."),
        ("Analysis",      "lightbulb", "Choose OCR languages, Whisper size, and your LLM provider."),
        ("Skills",        "lightbulb", "Plugins that categorize captures into buckets."),
        ("Reports",       "document",  "How and when daily/weekly summaries are produced."),
        ("Capture",       "mic",       "Audio devices, recording details, and voice quick-notes."),
        ("Privacy",       "dismiss",   "Apps that should never be captured or analyzed."),
        ("Storage",       "folder",    "Disk retention for captures and summaries."),
        ("Data",          "save",      "Export or import your config, database, vectors, and reports."),
        ("Advanced",      "settings",  "Optional telemetry and troubleshooting controls."),
        ("Appearance",    "color",     "Theme, accent colour, and density."),
    )

    def __init__(
        self,
        config: RinConfig,
        *,
        learn_callback: Callable[[Callable[[TriggerBinding], None]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("RIN — Settings")
        self.setMinimumSize(780, 560)
        self._config = config
        self._learn_callback = learn_callback

        # Resolve the active theme up-front so we can tint nav icons to
        # match the muted text colour (Fluent's "neutralForeground2").
        try:
            theme = with_accent(resolve(config.ui.theme), config.ui.accent)
        except Exception:
            theme = LIGHT
        self._nav_color = theme.text_muted
        self._nav_color_selected = theme.text

        self._nav = QListWidget()
        self._nav.setProperty("role", "nav")
        self._nav.setFixedWidth(220)
        self._nav.setIconSize(QSize(18, 18))
        self._nav.setSpacing(0)
        self._nav.setFrameShape(QFrame.Shape.NoFrame)
        self._nav.setUniformItemSizes(True)
        for label, icon_name, _caption in self.NAV_ITEMS:
            item = QListWidgetItem(_nav_icon(icon_name, self._nav_color), "  " + label)
            self._nav.addItem(item)

        self._stack = QStackedWidget()
        self._build_trigger_tab()
        self._build_working_hours_tab()
        self._build_analysis_tab()
        self._build_skills_tab()
        self._build_reports_tab()
        self._build_capture_tab()
        self._build_privacy_tab()
        self._build_storage_tab()
        self._build_data_tab()
        self._build_advanced_tab()
        self._build_appearance_tab()

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        save_btn = QPushButton("Save")
        save_btn.setProperty("primary", True)
        save_btn.setMinimumWidth(96)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(96)
        cancel_btn.clicked.connect(self.reject)

        # Footer with top divider, matching Fluent dialog conventions.
        footer = QWidget()
        footer.setObjectName("footer")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(20, 10, 20, 12)
        footer_row.setSpacing(8)
        footer_row.addStretch()
        footer_row.addWidget(cancel_btn)
        footer_row.addWidget(save_btn)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._nav)
        body.addWidget(self._stack, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(body, 1)
        outer.addWidget(footer)

        self.load_from_config()

    # --- helpers ------------------------------------------------------------------

    def _add_page(self, page: QWidget) -> None:
        """Wrap a page with consistent margins + heading + scroll area.

        Pulls the heading text + caption from ``NAV_ITEMS`` so each page
        has a hero title and a small supporting line that explains what
        the section controls. Layout breathes — labels sit above inputs
        with explicit widths, hints sit immediately below the input they
        describe (handled by callers via ``_hint``).
        """

        idx = self._stack.count()
        title, _icon, caption = (
            self.NAV_ITEMS[idx] if idx < len(self.NAV_ITEMS) else ("", "", "")
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        wrapper = QWidget()
        col = QVBoxLayout(wrapper)
        col.setContentsMargins(32, 28, 32, 16)
        col.setSpacing(8)

        if title:
            heading = QLabel(title)
            heading.setProperty("heading", "h1")
            col.addWidget(heading)
        if caption:
            sub = QLabel(caption)
            sub.setProperty("role", "caption")
            sub.setWordWrap(True)
            col.addWidget(sub)
        col.addSpacing(12)

        col.addWidget(page)
        col.addStretch(1)
        scroll.setWidget(wrapper)
        self._stack.addWidget(scroll)

    @staticmethod
    def _form() -> QFormLayout:
        """Construct a Fluent-style label-ABOVE-input form layout."""

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)
        return form

    @staticmethod
    def _heading(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("heading", "h2")
        return lbl

    @staticmethod
    def _label(text: str) -> QLabel:
        """Field label (small SemiBold caption above its input)."""

        lbl = QLabel(text)
        lbl.setProperty("role", "field-label")
        return lbl

    @staticmethod
    def _hint(text: str) -> QLabel:
        """Hint text below an input — slightly muted, smaller, no decoration."""

        lbl = QLabel(text)
        lbl.setProperty("role", "field-hint")
        lbl.setWordWrap(True)
        return lbl

    @staticmethod
    def _fixed(widget: QWidget, width: int) -> QWidget:
        """Force a fixed width on an input — QFormLayout otherwise stretches it."""

        widget.setFixedWidth(width)
        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return widget

    @staticmethod
    def _section_spacer(form: QFormLayout, height: int = 8) -> None:
        spacer = QWidget()
        spacer.setFixedHeight(height)
        form.addRow(spacer)

    def _selected_ocr_languages(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._ocr_languages.selectedItems()
        ]

    def _set_selected_ocr_languages(self, languages: list[str]) -> None:
        wanted = set(languages)
        for index in range(self._ocr_languages.count()):
            item = self._ocr_languages.item(index)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in wanted)

    def _update_whisper_hint(self, model_name: str) -> None:
        self._whisper_hint.setText(WHISPER_MODEL_HINTS.get(model_name, ""))

    def _sync_quick_note_state(self, _checked: bool | None = None) -> None:
        enabled = self._quick_note_enabled.isChecked()
        self._quick_note_seconds.setEnabled(enabled)
        self._quick_note_audio_combo.setEnabled(enabled)

    def _sync_telemetry_state(self, _checked: bool | None = None) -> None:
        enabled = self._telemetry_enabled.isChecked()
        self._telemetry_dsn.setEnabled(enabled)

    def _browse_obsidian_vault(self) -> None:
        current = self._obsidian_vault_path.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose Obsidian vault", current)
        if chosen:
            self._obsidian_vault_path.setText(chosen)

    def _apply_form_to_config(self) -> None:
        c = self._config
        c.trigger.hold_threshold_ms = self._hold_spin.value()

        c.working_hours.enabled = self._wh_enabled.isChecked()
        c.working_hours.start_hour = self._wh_start.value()
        c.working_hours.end_hour = self._wh_end.value()
        c.working_hours.weekdays = [
            i for i, cb in enumerate(self._weekday_checks) if cb.isChecked()
        ]
        c.working_hours.idle_threshold_minutes = self._idle_minutes.value()

        c.llm.name = self._llm_combo.currentText()
        c.llm.model = self._llm_model.text().strip()
        c.llm.reasoning_effort = self._effort_combo.currentText()
        c.llm.azure_endpoint = self._azure_endpoint.text().strip() or None
        c.llm.azure_deployment = self._azure_deployment.text().strip() or None
        c.llm.timeout_seconds = self._llm_timeout.value()
        c.analysis.hourly_enabled = self._hourly_enabled.isChecked()
        c.analysis.require_idle_or_offhours = self._require_idle.isChecked()
        c.analysis.ocr_languages = self._selected_ocr_languages() or ["en", "ch_sim"]
        c.analysis.whisper_model = self._whisper_combo.currentText()  # type: ignore[assignment]

        c.reports.frequency = self._report_combo.currentText()
        c.reports.deliver_via_notification = self._notify_check.isChecked()
        c.reports.calendar_provider = self._calendar_provider_combo.currentText()
        c.reports.obsidian_vault_path = self._obsidian_vault_path.text().strip() or None

        c.storage.raw_retention_days = self._retention_spin.value()
        c.storage.keep_summaries_forever = self._keep_summaries.isChecked()
        c.storage.min_free_space_gb = self._min_space.value()

        c.capture.audio_device = self._audio_combo.currentText().strip() or None
        c.capture.audio_sample_rate = self._sample_rate_spin.value()
        c.capture.audio_channels = self._channels_spin.value()
        c.capture.enable_quick_note = self._quick_note_enabled.isChecked()
        c.capture.quick_note_seconds = self._quick_note_seconds.value()
        c.capture.quick_note_audio_device = self._quick_note_audio_combo.currentText().strip() or None

        c.privacy.app_blacklist = [
            line.strip()
            for line in self._privacy_blacklist.toPlainText().splitlines()
            if line.strip()
        ]
        c.privacy.encrypt_at_rest = self._privacy_encrypt_at_rest.isChecked()
        c.paused = self._privacy_pause_check.isChecked()

        for mode, rb in self._theme_radios.items():
            if rb.isChecked():
                c.ui.theme = mode  # type: ignore[assignment]
                break
        for accent, rb in self._accent_radios.items():
            if rb.isChecked():
                c.ui.accent = accent  # type: ignore[assignment]
                break
        c.ui.density = self._density_combo.currentText()  # type: ignore[assignment]

        c.telemetry.enabled = self._telemetry_enabled.isChecked()
        c.telemetry.dsn = self._telemetry_dsn.text().strip() or None

    def _export_everything(self) -> None:
        from ..utils.data_export import export_all

        self._apply_form_to_config()
        self._config.save()
        default_name = f"rin-export-{datetime.now():%Y%m%d-%H%M%S}.zip"
        default_path = str(Path.home() / default_name)
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export everything",
            default_path,
            "Zip archives (*.zip)",
        )
        if not selected:
            return
        try:
            export_all(Path(selected))
        except Exception as exc:
            log.warning(f"Data export failed: {exc}")
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Export complete",
            "Saved a portable RIN backup zip. API keys stay redacted and must be re-entered after import.",
        )

    def _import_everything(self) -> None:
        from ..storage import db, init_db, vector_store
        from ..utils.data_export import import_all

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Import RIN backup",
            str(Path.home()),
            "Zip archives (*.zip)",
        )
        if not selected:
            return

        answer = QMessageBox.warning(
            self,
            "Import backup",
            (
                "This overwrites config.toml, rin.db, reports, Chroma data, and summaries in the current RIN data directory.\n\n"
                "API keys are intentionally redacted from exports and will need to be entered again after import. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        db.reset()
        vector_store.reset()
        try:
            import_all(Path(selected), force=True)
            updated = RinConfig.load()
            for field_name in type(self._config).model_fields:
                setattr(self._config, field_name, getattr(updated, field_name))
            init_db()
        except Exception as exc:
            init_db()
            log.warning(f"Data import failed: {exc}")
            QMessageBox.warning(self, "Import failed", str(exc))
            return

        self.load_from_config()
        self.config_saved.emit(self._config)
        QMessageBox.information(
            self,
            "Import complete",
            "Backup restored. RIN has reloaded the config; restarting is recommended for a fully clean state.",
        )

    # --- tab builders -------------------------------------------------------------

    def _build_trigger_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        # Trigger row: present the bound key as a "chip" with the
        # Learn-new-button trigger right next to it. Both inside a card
        # so the relationship is unmistakable.
        self._binding_label = QLabel("(unset)")
        self._binding_label.setObjectName("trigger_label")
        self._binding_label.setProperty("role", "chip")
        self._binding_label.setProperty("accent", True)
        self._binding_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._binding_label.setMinimumHeight(28)
        self._learn_button = QPushButton("Learn new button…")
        self._learn_button.clicked.connect(self._on_learn_clicked)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._binding_label, 0, Qt.AlignmentFlag.AlignLeft)
        row.addStretch(1)
        row.addWidget(self._learn_button, 0)
        form.addRow(self._label("Trigger button"), _wrap(row))

        self._hold_spin = QSpinBox()
        self._hold_spin.setRange(100, 5000)
        self._hold_spin.setSingleStep(50)
        self._hold_spin.setSuffix(" ms")
        self._fixed(self._hold_spin, _W_NUMBER)
        form.addRow(self._label("Hold threshold"), self._hold_spin)
        form.addRow(self._hint(
            "Tap the trigger to take a screenshot; hold past this threshold "
            "to start a video + audio recording. Release to stop."
        ))

        self._add_page(page)

    def _build_working_hours_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._wh_enabled = QCheckBox("Apply working-hours gate to hourly analysis")
        form.addRow(self._wh_enabled)
        form.addRow(self._hint(
            "Outside these hours (or when idle), RIN runs OCR + LLM on new captures."
        ))

        self._section_spacer(form)

        self._wh_start = QSpinBox()
        self._wh_start.setRange(0, 23)
        self._wh_start.setSuffix(" h")
        self._fixed(self._wh_start, 96)
        self._wh_end = QSpinBox()
        self._wh_end.setRange(0, 23)
        self._wh_end.setSuffix(" h")
        self._fixed(self._wh_end, 96)
        hours_row = QHBoxLayout()
        hours_row.setSpacing(8)
        hours_row.setContentsMargins(0, 0, 0, 0)
        from_lbl = QLabel("From")
        from_lbl.setProperty("muted", True)
        to_lbl = QLabel("to")
        to_lbl.setProperty("muted", True)
        hours_row.addWidget(from_lbl)
        hours_row.addWidget(self._wh_start)
        hours_row.addSpacing(8)
        hours_row.addWidget(to_lbl)
        hours_row.addWidget(self._wh_end)
        hours_row.addStretch()
        form.addRow(self._label("Hours"), _wrap(hours_row))

        self._weekday_checks: list[QCheckBox] = []
        wd_row = QHBoxLayout()
        wd_row.setSpacing(10)
        wd_row.setContentsMargins(0, 0, 0, 0)
        for label in WEEKDAY_NAMES:
            cb = QCheckBox(label)
            self._weekday_checks.append(cb)
            wd_row.addWidget(cb)
        wd_row.addStretch()
        form.addRow(self._label("Workdays"), _wrap(wd_row))

        self._idle_minutes = QSpinBox()
        self._idle_minutes.setRange(1, 240)
        self._idle_minutes.setSuffix(" min")
        self._fixed(self._idle_minutes, _W_NUMBER)
        form.addRow(self._label("Idle threshold"), self._idle_minutes)

        self._add_page(page)

    def _build_analysis_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._llm_combo = QComboBox()
        self._llm_combo.addItems(LLM_NAMES)
        self._fixed(self._llm_combo, _W_PICKER)
        form.addRow(self._label("Provider"), self._llm_combo)
        form.addRow(self._hint(
            "Copilot CLI is the default and needs no API key — install with "
            "`winget install GitHub.cli` then `gh extension install github/gh-copilot`."
        ))

        self._llm_model = QLineEdit()
        self._llm_model.setPlaceholderText("Provider default (leave blank)")
        self._fixed(self._llm_model, _W_TEXT)
        form.addRow(self._label("Model"), self._llm_model)

        self._effort_combo = QComboBox()
        self._effort_combo.addItems(REASONING_EFFORTS)
        self._fixed(self._effort_combo, _W_PICKER)
        self._effort_combo.setToolTip(
            "Copilot CLI only — reasoning effort. Leave blank to use the model's default."
        )
        form.addRow(self._label("Reasoning effort"), self._effort_combo)

        self._azure_endpoint = QLineEdit()
        self._azure_endpoint.setPlaceholderText("https://your-resource.openai.azure.com")
        self._fixed(self._azure_endpoint, _W_URL)
        form.addRow(self._label("Azure endpoint"), self._azure_endpoint)

        self._azure_deployment = QLineEdit()
        self._fixed(self._azure_deployment, _W_TEXT)
        form.addRow(self._label("Azure deployment"), self._azure_deployment)

        self._llm_timeout = QSpinBox()
        self._llm_timeout.setRange(5, 600)
        self._llm_timeout.setSuffix(" s")
        self._fixed(self._llm_timeout, _W_NUMBER)
        form.addRow(self._label("Request timeout"), self._llm_timeout)

        self._section_spacer(form)

        self._hourly_enabled = QCheckBox("Run hourly auto-analysis")
        form.addRow(self._hourly_enabled)
        self._require_idle = QCheckBox(
            "Only analyze outside working hours OR when idle"
        )
        form.addRow(self._require_idle)

        self._section_spacer(form)

        self._ocr_languages = QListWidget()
        self._ocr_languages.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._ocr_languages.setFixedWidth(_W_URL)
        self._ocr_languages.setFixedHeight(150)
        for code, label in OCR_LANGUAGE_OPTIONS:
            item = QListWidgetItem(f"{label} ({code})")
            item.setData(Qt.ItemDataRole.UserRole, code)
            self._ocr_languages.addItem(item)
        form.addRow(self._label("OCR languages"), self._ocr_languages)
        form.addRow(self._hint(
            "Use Ctrl+click to select multiple RapidOCR languages. Default: English + Simplified Chinese."
        ))

        self._whisper_combo = QComboBox()
        self._whisper_combo.addItems(WHISPER_MODEL_OPTIONS)
        self._fixed(self._whisper_combo, _W_PICKER)
        self._whisper_combo.currentTextChanged.connect(self._update_whisper_hint)
        form.addRow(self._label("Whisper model"), self._whisper_combo)
        self._whisper_hint = self._hint("")
        form.addRow(self._whisper_hint)

        self._add_page(page)

    def _build_skills_tab(self) -> None:
        """List discovered skills + per-skill enable toggle + Configure."""

        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        self._skill_cards_layout = QVBoxLayout()
        self._skill_cards_layout.setSpacing(10)
        col.addLayout(self._skill_cards_layout)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_folder = QPushButton("Open skills folder…")
        open_folder.setProperty("flat", True)
        open_folder.clicked.connect(self._open_skills_folder)
        actions.addStretch()
        actions.addWidget(open_folder)
        col.addLayout(actions)

        warn = QLabel(
            "Skills run inside RIN and see every capture's text. Only "
            "install skills from sources you trust."
        )
        warn.setProperty("role", "field-hint")
        warn.setWordWrap(True)
        col.addWidget(warn)

        self._populate_skill_cards()
        self._add_page(page)

    def _populate_skill_cards(self) -> None:
        """Rebuild the skill list from rin.skills.registry.discover()."""

        # Clear existing widgets in the layout (rebuild on every load).
        while self._skill_cards_layout.count():
            item = self._skill_cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        try:
            from ..skills.registry import discover
            loaded = discover(self._config)
        except Exception as exc:
            log.warning(f"skill discover failed: {exc}")
            loaded = []

        enabled = set(self._config.skills.enabled or [])
        self._skill_toggles: dict[str, QCheckBox] = {}

        if not loaded:
            empty = QLabel(
                "No skills discovered. Drop a folder with `skill.py` into the "
                "skills folder, then reopen Settings."
            )
            empty.setProperty("role", "field-hint")
            empty.setWordWrap(True)
            self._skill_cards_layout.addWidget(empty)
            return

        for ls in loaded:
            self._skill_cards_layout.addWidget(self._skill_card(ls, enabled))

    def _skill_card(self, loaded, enabled: set[str]) -> QWidget:
        skill = loaded.skill
        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        name_lbl = QLabel(skill.display_name)
        name_lbl.setProperty("heading", "h2")
        version_chip = QLabel(f"v{skill.version}")
        version_chip.setProperty("role", "chip")
        version_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        source_chip = QLabel(loaded.source.title())
        source_chip.setProperty("role", "chip")
        source_chip.setProperty(
            "accent", "true" if loaded.source == "builtin" else "false"
        )
        source_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(name_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addSpacing(4)
        top.addWidget(version_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(source_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        toggle = QCheckBox("Enabled")
        toggle.setChecked(skill.name in enabled)
        toggle.stateChanged.connect(
            lambda _state, name=skill.name: self._on_skill_toggled(name)
        )
        top.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self._skill_toggles[skill.name] = toggle
        outer.addLayout(top)

        if skill.description:
            desc = QLabel(skill.description)
            desc.setProperty("role", "field-hint")
            desc.setWordWrap(True)
            outer.addWidget(desc)

        return card

    def _on_skill_toggled(self, skill_name: str) -> None:
        enabled = list(self._config.skills.enabled or [])
        if self._skill_toggles[skill_name].isChecked():
            if skill_name not in enabled:
                enabled.append(skill_name)
        else:
            enabled = [n for n in enabled if n != skill_name]
        self._config.skills.enabled = enabled

    def _open_skills_folder(self) -> None:
        import os

        try:
            from .. import paths

            path = paths.skills_dir()
        except Exception as exc:
            log.warning(f"Cannot open skills folder: {exc}")
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            log.warning(f"os.startfile failed for {path}: {exc}")

    def _build_reports_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._report_combo = QComboBox()
        self._report_combo.addItems(REPORT_FREQUENCIES)
        self._fixed(self._report_combo, _W_PICKER)
        form.addRow(self._label("Frequency"), self._report_combo)
        form.addRow(self._hint(
            "Daily reports are generated at 23:50 local time; weekly reports on Sunday."
        ))

        self._section_spacer(form)

        self._notify_check = QCheckBox("Show a notification when a report is ready")
        form.addRow(self._notify_check)

        self._section_spacer(form)

        self._calendar_provider_combo = QComboBox()
        self._calendar_provider_combo.addItems(["none", "outlook", "google"])
        self._fixed(self._calendar_provider_combo, _W_PICKER)
        self._calendar_provider_combo.currentTextChanged.connect(self._sync_calendar_auth_state)
        self._calendar_sign_in_button = QPushButton("Sign in…")
        self._calendar_sign_in_button.clicked.connect(self._start_calendar_sign_in)
        self._calendar_sign_in_spinner = Spinner(size=18, accent=self._nav_color_selected)
        self._calendar_sign_in_spinner.hide()
        self._calendar_sign_in_busy = False
        calendar_row = QHBoxLayout()
        calendar_row.setContentsMargins(0, 0, 0, 0)
        calendar_row.setSpacing(8)
        calendar_row.addWidget(self._calendar_provider_combo)
        calendar_row.addWidget(self._calendar_sign_in_button, 0)
        calendar_row.addWidget(self._calendar_sign_in_spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        calendar_row.addStretch()
        form.addRow(self._label("Calendar provider"), _wrap(calendar_row))
        form.addRow(self._hint(
            "Optional read-only Outlook or Google Calendar context for reports. "
            "OAuth tokens stay in your OS keyring."
        ))
        self._sync_calendar_auth_state()

        self._section_spacer(form)

        self._obsidian_vault_path = QLineEdit()
        self._obsidian_vault_path.setPlaceholderText("Optional Obsidian vault folder")
        self._fixed(self._obsidian_vault_path, _W_URL)
        obsidian_browse = QPushButton("Browse…")
        obsidian_browse.clicked.connect(self._browse_obsidian_vault)
        obsidian_row = QHBoxLayout()
        obsidian_row.setContentsMargins(0, 0, 0, 0)
        obsidian_row.setSpacing(8)
        obsidian_row.addWidget(self._obsidian_vault_path)
        obsidian_row.addWidget(obsidian_browse, 0)
        obsidian_row.addStretch()
        form.addRow(self._label("Obsidian vault"), _wrap(obsidian_row))
        form.addRow(self._hint(
            "If set, generated markdown can link cleanly into your existing Obsidian notes workspace."
        ))

        self._add_page(page)

    def _sync_calendar_auth_state(self, _provider_name: str | None = None) -> None:
        enabled = self._calendar_provider_combo.currentText() != "none"
        self._calendar_sign_in_button.setEnabled(enabled and not self._calendar_sign_in_busy)
        self._calendar_provider_combo.setEnabled(not self._calendar_sign_in_busy)
        if self._calendar_sign_in_busy:
            self._calendar_sign_in_spinner.start()
            self._calendar_sign_in_spinner.show()
        else:
            self._calendar_sign_in_spinner.stop()
            self._calendar_sign_in_spinner.hide()

    def _start_calendar_sign_in(self) -> None:
        provider_name = self._calendar_provider_combo.currentText()
        if provider_name == "none":
            return
        from ..reports.integrations.factory import make_calendar_provider

        cfg = self._config.model_copy(deep=True)
        cfg.reports.calendar_provider = provider_name
        provider = make_calendar_provider(cfg)
        if provider is None:
            QMessageBox.warning(
                self,
                "Calendar sign-in unavailable",
                "Install RIN with the calendar optional dependencies to enable this provider.",
            )
            return
        authenticate = getattr(provider, "authenticate", None)
        if not callable(authenticate):
            QMessageBox.warning(
                self,
                "Calendar sign-in unavailable",
                "The selected provider does not expose an OAuth sign-in flow.",
            )
            return

        class _CalendarSignInSignals(QObject):
            done = Signal(str)
            failed = Signal(str)

        class _CalendarSignInTask(QRunnable):
            def __init__(self, callback, provider_label: str, signals: _CalendarSignInSignals) -> None:
                super().__init__()
                self._callback = callback
                self._provider_label = provider_label
                self._signals = signals

            def run(self) -> None:  # pragma: no cover - thread plumbing
                try:
                    self._callback()
                    self._signals.done.emit(self._provider_label)
                except Exception as exc:
                    self._signals.failed.emit(str(exc))

        self._calendar_sign_in_busy = True
        self._sync_calendar_auth_state()
        if not hasattr(self, "_calendar_auth_pool"):
            self._calendar_auth_pool = QThreadPool.globalInstance()
        self._calendar_sign_in_signals = _CalendarSignInSignals()
        self._calendar_sign_in_signals.done.connect(
            self._on_calendar_sign_in_done,
            Qt.ConnectionType.QueuedConnection,
        )
        self._calendar_sign_in_signals.failed.connect(
            self._on_calendar_sign_in_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._calendar_auth_pool.start(
            _CalendarSignInTask(authenticate, provider_name, self._calendar_sign_in_signals)
        )

    def _on_calendar_sign_in_done(self, provider_name: str) -> None:
        self._calendar_sign_in_busy = False
        self._sync_calendar_auth_state()
        QMessageBox.information(
            self,
            "Calendar connected",
            f"Signed in to {provider_name.title()} calendar. Save settings to use it in future reports.",
        )

    def _on_calendar_sign_in_failed(self, msg: str) -> None:
        self._calendar_sign_in_busy = False
        self._sync_calendar_auth_state()
        log.warning(f"Calendar sign-in failed: {msg}")
        QMessageBox.warning(self, "Calendar sign-in failed", msg)

    def _build_privacy_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        # --- Pause captures (moved here from the tray menu in v0.7.1) -----
        #
        # Two controls cover both the "indefinite" and "timed" pause modes
        # that previously lived in the tray right-click menu. The toggle is
        # persisted to `cfg.paused` on Save like any other field; the timed
        # buttons apply immediately because they are time-sensitive actions
        # the user would otherwise have to Save before they took effect.

        self._privacy_pause_check = QCheckBox(
            "Pause captures (skip every screenshot/recording until resumed)"
        )
        form.addRow(self._privacy_pause_check)
        form.addRow(self._hint(
            "Persists across restarts. The global Ctrl+Alt+Shift+P panic "
            "hotkey is a separate, RAM-only quick toggle for emergency use."
        ))

        # Timed pause row: status + Pause 15min + Resume now
        timed_row = QHBoxLayout()
        timed_row.setSpacing(8)
        timed_row.setContentsMargins(0, 0, 0, 0)
        self._privacy_timed_status = QLabel("Not paused")
        self._privacy_timed_status.setProperty("role", "field-hint")
        self._privacy_pause_15_btn = QPushButton("Pause for 15 minutes")
        self._privacy_pause_15_btn.clicked.connect(
            lambda: self._apply_timed_pause(minutes=15)
        )
        self._privacy_pause_60_btn = QPushButton("Pause for 1 hour")
        self._privacy_pause_60_btn.clicked.connect(
            lambda: self._apply_timed_pause(minutes=60)
        )
        self._privacy_resume_btn = QPushButton("Resume now")
        self._privacy_resume_btn.setProperty("flat", True)
        self._privacy_resume_btn.clicked.connect(self._clear_timed_pause)
        timed_row.addWidget(self._privacy_timed_status, 1)
        timed_row.addWidget(self._privacy_pause_15_btn)
        timed_row.addWidget(self._privacy_pause_60_btn)
        timed_row.addWidget(self._privacy_resume_btn)
        form.addRow(self._label("Timed pause"), _wrap(timed_row))
        form.addRow(self._hint(
            "Timed pauses apply immediately and persist across restarts. "
            "They expire automatically — no Save required."
        ))

        self._section_spacer(form)

        # --- App blacklist + at-rest encryption --------------------------
        self._privacy_blacklist = QPlainTextEdit()
        self._privacy_blacklist.setPlaceholderText("1Password.exe\nKeePassXC.exe")
        self._privacy_blacklist.setFixedHeight(160)
        form.addRow(self._label("App blacklist"), self._privacy_blacklist)
        form.addRow(self._hint(
            "One app or executable name per line. Captures from matching apps can be skipped elsewhere in the app."
        ))

        self._section_spacer(form)

        self._privacy_encrypt_at_rest = QCheckBox(
            "Encrypt captures at rest (Windows DPAPI)"
        )
        form.addRow(self._privacy_encrypt_at_rest)
        form.addRow(self._hint(
            "Uses a per-user AES-256 key sealed by Windows DPAPI. Analysis may be slightly slower because encrypted PNG/MP4 files must be decrypted before OCR or transcription."
        ))

        self._add_page(page)

    # --- timed-pause helpers (immediate-apply, not gated by Save) ----------

    def _apply_timed_pause(self, *, minutes: int) -> None:
        """Write ``cfg.privacy.paused_until_iso`` and persist immediately.

        Updates the live config on disk so the change is visible to the
        running ``CaptureService`` without the user having to Save the
        whole dialog.
        """

        from datetime import datetime, timedelta

        until = datetime.now() + timedelta(minutes=minutes)
        self._config.privacy.paused_until_iso = until.isoformat()
        try:
            self._config.save()
        except Exception as exc:
            log.error(f"Failed to persist timed pause: {exc}")
            return
        self._refresh_timed_pause_status()

    def _clear_timed_pause(self) -> None:
        """Cancel any active timed pause."""

        self._config.privacy.paused_until_iso = None
        try:
            self._config.save()
        except Exception as exc:
            log.error(f"Failed to clear timed pause: {exc}")
            return
        self._refresh_timed_pause_status()

    def _refresh_timed_pause_status(self) -> None:
        """Update the inline status label + button enabled-state."""

        from datetime import datetime

        until_iso = self._config.privacy.paused_until_iso
        until = None
        if until_iso:
            try:
                until = datetime.fromisoformat(until_iso)
            except ValueError:
                until = None
        now = datetime.now(until.tzinfo) if (until and until.tzinfo) else datetime.now()
        active = until is not None and until > now
        if active:
            self._privacy_timed_status.setText(
                f"Paused until {until.strftime('%H:%M')}"
            )
            self._privacy_resume_btn.setEnabled(True)
        else:
            self._privacy_timed_status.setText("Not paused")
            self._privacy_resume_btn.setEnabled(False)

    def _build_storage_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(1, 3650)
        self._retention_spin.setSuffix(" days")
        self._fixed(self._retention_spin, _W_NUMBER)
        form.addRow(self._label("Keep raw captures for"), self._retention_spin)
        form.addRow(self._hint(
            "Older PNG/MP4 files are removed; their summaries remain in the database."
        ))

        self._section_spacer(form)

        self._keep_summaries = QCheckBox("Keep AI summaries forever")
        form.addRow(self._keep_summaries)

        self._min_space = QSpinBox()
        self._min_space.setRange(1, 1000)
        self._min_space.setSuffix(" GB")
        self._fixed(self._min_space, _W_NUMBER)
        form.addRow(self._label("Minimum free space"), self._min_space)
        form.addRow(self._hint(
            "RIN pauses captures when the disk drops below this threshold."
        ))

        self._add_page(page)

    def _build_capture_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._audio_combo = QComboBox()
        self._audio_combo.setEditable(True)
        self._fixed(self._audio_combo, _W_URL)
        self._audio_combo.setToolTip(
            "DirectShow audio device to mix into video recordings. "
            "Leave blank to record video only."
        )
        self._refresh_audio_button = QPushButton("Refresh")
        self._refresh_audio_button.clicked.connect(self._refresh_audio_devices)

        # Inline spinner that takes the Refresh button's place while a
        # device-enumeration shells out to ffmpeg (typically 1-3 s).
        self._refresh_audio_spinner = Spinner(size=18, accent=self._nav_color_selected)
        self._refresh_audio_spinner.hide()

        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        audio_row.setContentsMargins(0, 0, 0, 0)
        audio_row.addWidget(self._audio_combo, 0)
        audio_row.addWidget(self._refresh_audio_button, 0)
        audio_row.addWidget(self._refresh_audio_spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        audio_row.addStretch()
        form.addRow(self._label("Audio device"), _wrap(audio_row))
        form.addRow(self._hint(
            "Enable 'Stereo Mix' in Windows Sound settings to capture "
            "system audio (not just the mic)."
        ))

        self._section_spacer(form)

        self._sample_rate_spin = QSpinBox()
        self._sample_rate_spin.setRange(8000, 192000)
        self._sample_rate_spin.setSingleStep(1000)
        self._sample_rate_spin.setSuffix(" Hz")
        self._fixed(self._sample_rate_spin, _W_NUMBER)
        form.addRow(self._label("Sample rate"), self._sample_rate_spin)

        self._channels_spin = QSpinBox()
        self._channels_spin.setRange(1, 8)
        self._fixed(self._channels_spin, 88)
        form.addRow(self._label("Audio channels"), self._channels_spin)

        self._section_spacer(form)

        self._quick_note_enabled = QCheckBox(
            "Enable 5-second voice quick-note after screenshot"
        )
        self._quick_note_enabled.toggled.connect(self._sync_quick_note_state)
        form.addRow(self._quick_note_enabled)

        self._quick_note_seconds = QSpinBox()
        self._quick_note_seconds.setRange(1, 60)
        self._quick_note_seconds.setSuffix(" s")
        self._fixed(self._quick_note_seconds, _W_NUMBER)
        form.addRow(self._label("Quick-note duration"), self._quick_note_seconds)

        self._quick_note_audio_combo = QComboBox()
        self._quick_note_audio_combo.setEditable(True)
        self._fixed(self._quick_note_audio_combo, _W_URL)
        form.addRow(self._label("Quick-note audio device"), self._quick_note_audio_combo)
        form.addRow(self._hint(
            "Uses the same DirectShow device list as the recording audio picker above."
        ))

        self._add_page(page)

    def _build_data_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        export_btn = QPushButton("Export everything to zip…")
        export_btn.setProperty("primary", True)
        export_btn.clicked.connect(self._export_everything)
        form.addRow(export_btn)
        form.addRow(self._hint(
            "Creates a zip with a redacted config.toml, a live SQLite snapshot, Chroma data, reports, and analysis summaries."
        ))

        self._section_spacer(form)

        import_btn = QPushButton("Import from zip…")
        import_btn.clicked.connect(self._import_everything)
        form.addRow(import_btn)
        form.addRow(self._hint(
            "Restores an export into the current RIN data directory. API keys remain redacted by design."
        ))

        self._add_page(page)

    def _build_advanced_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._telemetry_enabled = QCheckBox("Enable Sentry error telemetry")
        self._telemetry_enabled.toggled.connect(self._sync_telemetry_state)
        form.addRow(self._telemetry_enabled)
        form.addRow(self._hint(
            "Optional and off by default. Install the telemetry extra to activate sentry-sdk at startup."
        ))

        self._section_spacer(form)

        self._telemetry_dsn = QLineEdit()
        self._telemetry_dsn.setPlaceholderText("https://public@example.ingest.sentry.io/1")
        self._fixed(self._telemetry_dsn, _W_URL)
        form.addRow(self._label("Sentry DSN"), self._telemetry_dsn)

        self._sentry_link = QLabel(
            '<a href="https://develop.sentry.dev/self-hosted/">Sentry self-host</a>'
        )
        self._sentry_link.setProperty("role", "field-hint")
        self._sentry_link.setOpenExternalLinks(True)
        form.addRow(self._sentry_link)

        self._add_page(page)

    def _build_appearance_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._theme_group = QButtonGroup(self)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(20)
        theme_row.setContentsMargins(0, 0, 0, 0)
        self._theme_radios: dict[str, QRadioButton] = {}
        for mode in THEME_MODES:
            label = {"auto": "Follow Windows", "light": "Light", "dark": "Dark"}[mode]
            rb = QRadioButton(label)
            self._theme_radios[mode] = rb
            self._theme_group.addButton(rb)
            theme_row.addWidget(rb)
        theme_row.addStretch()
        form.addRow(self._label("Theme"), _wrap(theme_row))

        self._accent_group = QButtonGroup(self)
        accent_row = QHBoxLayout()
        accent_row.setSpacing(20)
        accent_row.setContentsMargins(0, 0, 0, 0)
        self._accent_radios: dict[str, QRadioButton] = {}
        accent_labels = {"blue": "Blue", "purple": "Purple", "teal": "Teal", "orange": "Orange"}
        for accent in ACCENT_OPTIONS:
            rb = QRadioButton(accent_labels[accent])
            self._accent_radios[accent] = rb
            self._accent_group.addButton(rb)
            accent_row.addWidget(rb)
        accent_row.addStretch()
        form.addRow(self._label("Accent color"), _wrap(accent_row))

        self._density_combo = QComboBox()
        self._density_combo.addItems(["comfortable", "compact"])
        self._fixed(self._density_combo, _W_PICKER)
        self._density_combo.setToolTip(
            "Spacing density for buttons, lists, and inputs."
        )
        form.addRow(self._label("Density"), self._density_combo)

        form.addRow(self._hint(
            "Changes apply immediately on Save — no restart needed."
        ))

        self._add_page(page)

    # --- load / save --------------------------------------------------------------

    def load_from_config(self) -> None:
        c = self._config
        self._binding_label.setText(self._format_binding(c.trigger))
        self._hold_spin.setValue(c.trigger.hold_threshold_ms)

        self._wh_enabled.setChecked(c.working_hours.enabled)
        self._wh_start.setValue(c.working_hours.start_hour)
        self._wh_end.setValue(c.working_hours.end_hour)
        active = set(c.working_hours.weekdays)
        for i, cb in enumerate(self._weekday_checks):
            cb.setChecked(i in active)
        self._idle_minutes.setValue(c.working_hours.idle_threshold_minutes)

        self._llm_combo.setCurrentText(c.llm.name)
        self._llm_model.setText(c.llm.model or "")
        self._effort_combo.setCurrentText(c.llm.reasoning_effort or "")
        self._azure_endpoint.setText(c.llm.azure_endpoint or "")
        self._azure_deployment.setText(c.llm.azure_deployment or "")
        self._llm_timeout.setValue(c.llm.timeout_seconds)
        self._hourly_enabled.setChecked(c.analysis.hourly_enabled)
        self._require_idle.setChecked(c.analysis.require_idle_or_offhours)
        self._set_selected_ocr_languages(c.analysis.ocr_languages)
        self._whisper_combo.setCurrentText(c.analysis.whisper_model)
        self._update_whisper_hint(c.analysis.whisper_model)

        self._report_combo.setCurrentText(c.reports.frequency)
        self._notify_check.setChecked(c.reports.deliver_via_notification)
        self._calendar_provider_combo.setCurrentText(c.reports.calendar_provider)
        self._sync_calendar_auth_state()
        self._obsidian_vault_path.setText(c.reports.obsidian_vault_path or "")

        self._retention_spin.setValue(c.storage.raw_retention_days)
        self._keep_summaries.setChecked(c.storage.keep_summaries_forever)
        self._min_space.setValue(c.storage.min_free_space_gb)

        self._privacy_blacklist.setPlainText("\n".join(c.privacy.app_blacklist))
        self._privacy_encrypt_at_rest.setChecked(c.privacy.encrypt_at_rest)
        self._privacy_pause_check.setChecked(c.paused)
        self._refresh_timed_pause_status()

        # Capture tab — seed the audio combos with the currently saved
        # device values so the user sees *something* immediately, then enumerate
        # the real device list on a worker (ffmpeg shells take 1-3 s).
        initial_device = c.capture.audio_device or ""
        quick_note_device = c.capture.quick_note_audio_device or ""
        self._apply_audio_devices([], initial=initial_device, quick_note_initial=quick_note_device)
        self._refresh_audio_devices()
        self._sample_rate_spin.setValue(c.capture.audio_sample_rate)
        self._channels_spin.setValue(c.capture.audio_channels)
        self._quick_note_enabled.setChecked(c.capture.enable_quick_note)
        self._quick_note_seconds.setValue(c.capture.quick_note_seconds)
        self._sync_quick_note_state()

        self._telemetry_enabled.setChecked(c.telemetry.enabled)
        self._telemetry_dsn.setText(c.telemetry.dsn or "")
        self._sync_telemetry_state()

        # Appearance tab.
        self._theme_radios[c.ui.theme].setChecked(True)
        self._accent_radios[c.ui.accent].setChecked(True)
        self._density_combo.setCurrentText(c.ui.density)

    def _on_save(self) -> None:
        self._apply_form_to_config()
        self._config.save()
        log.info("Settings saved")
        self.config_saved.emit(self._config)
        self.accept()

    # --- learn-mode glue ----------------------------------------------------------

    def _on_learn_clicked(self) -> None:
        if self._learn_callback is None:
            self._binding_label.setText("(learn-mode not wired up)")
            return
        self._binding_label.setText("Press any button…")
        self._learn_button.setEnabled(False)
        self._learn_callback(self._on_binding_learned)

    def _on_binding_learned(self, binding: TriggerBinding) -> None:
        self._config.trigger = binding
        self._binding_label.setText(self._format_binding(binding))
        self._learn_button.setEnabled(True)

    @staticmethod
    def _format_binding(binding: TriggerBinding) -> str:
        """Pretty-print a binding for the trigger chip."""

        if binding.source == "unset":
            return "Not set"
        if binding.source == "keyboard" and binding.key:
            return binding.key.upper()
        if binding.source == "mouse" and binding.key:
            return f"Mouse · {binding.key}"
        if binding.source == "hid":
            return f"HID {binding.vendor_id:#06x}:{binding.product_id:#06x}"
        return binding.label or binding.source

    # --- audio device picker ------------------------------------------------------

    def _populate_audio_combo(
        self,
        *,
        initial: str = "",
        quick_note_initial: str = "",
    ) -> None:
        """Synchronously enumerate + populate. Used at dialog open time only;
        manual refresh after that is dispatched through a worker."""

        from ..capture import list_dshow_audio_devices

        try:
            devices = list_dshow_audio_devices()
        except Exception as exc:
            log.warning(f"Audio device enumeration failed: {exc}")
            devices = []
        self._apply_audio_devices(
            devices,
            initial=initial,
            quick_note_initial=quick_note_initial,
        )

    def _apply_audio_devices(
        self,
        devices,
        *,
        initial: str = "",
        quick_note_initial: str = "",
    ) -> None:
        """Repopulate the audio combos from a list of device names."""

        combos = (
            (self._audio_combo, initial),
            (self._quick_note_audio_combo, quick_note_initial),
        )
        for combo, current in combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            for name in devices:
                combo.addItem(name)
            if current and combo.findText(current) == -1:
                combo.addItem(current)
            combo.setCurrentText(current)
            combo.blockSignals(False)

    def _refresh_audio_devices(self) -> None:
        """Async refresh: hide button, spin, repopulate on completion."""

        current = self._audio_combo.currentText().strip()
        quick_note_current = self._quick_note_audio_combo.currentText().strip()
        self._refresh_audio_button.setVisible(False)
        self._refresh_audio_spinner.set_accent(
            with_accent(resolve(self._config.ui.theme), self._config.ui.accent).accent
        )
        self._refresh_audio_spinner.show()
        self._refresh_audio_spinner.start()

        if not hasattr(self, "_audio_pool"):
            self._audio_pool = QThreadPool.globalInstance()
            self._audio_signals = _AudioRefreshSignals()
            self._audio_signals.done.connect(self._on_audio_refresh_done)
            self._audio_signals.failed.connect(self._on_audio_refresh_failed)
        self._pending_audio_initial = current
        self._pending_quick_note_audio_initial = quick_note_current
        self._audio_pool.start(_AudioRefreshTask(self._audio_signals))

    def _on_audio_refresh_done(self, devices: list) -> None:
        self._apply_audio_devices(
            devices,
            initial=getattr(self, "_pending_audio_initial", ""),
            quick_note_initial=getattr(self, "_pending_quick_note_audio_initial", ""),
        )
        self._refresh_audio_spinner.stop()
        self._refresh_audio_spinner.hide()
        self._refresh_audio_button.setVisible(True)

    def _on_audio_refresh_failed(self, msg: str) -> None:
        log.warning(f"Audio refresh failed: {msg}")
        # Keep whatever was already in the combo; just stop spinning.
        self._refresh_audio_spinner.stop()
        self._refresh_audio_spinner.hide()
        self._refresh_audio_button.setVisible(True)
        self._refresh_audio_button.setToolTip(f"Last refresh failed: {msg}")


def _wrap(layout) -> QWidget:
    """Wrap a layout in a transparent ``QWidget`` so it can sit in a ``QFormLayout``."""

    w = QWidget()
    w.setLayout(layout)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return w


class _AudioRefreshSignals(QObject):
    done = Signal(list)
    failed = Signal(str)


class _AudioRefreshTask(QRunnable):
    """Run :func:`list_dshow_audio_devices` on a worker thread."""

    def __init__(self, signals: _AudioRefreshSignals) -> None:
        super().__init__()
        self._signals = signals

    def run(self) -> None:  # pragma: no cover - thread plumbing
        try:
            from ..capture import list_dshow_audio_devices

            devices = list(list_dshow_audio_devices())
            self._signals.done.emit(devices)
        except Exception as exc:
            self._signals.failed.emit(str(exc))

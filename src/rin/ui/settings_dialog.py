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

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtCore import QThreadPool as QThreadPool
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import RinConfig, TriggerBinding
from ..utils.logging import get_logger
from .settings_common import (
    _nav_icon,
)
from .settings_tabs import _SettingsTabsMixin
from .theme import LIGHT, current_theme

log = get_logger(__name__)


class SettingsDialog(_SettingsTabsMixin, QDialog):
    config_saved = Signal(RinConfig)

    # Each tab: (label, icon, supporting caption).
    NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
        ("Trigger",       "keyboard",  "What button captures or starts a recording."),
        ("Working hours", "clock",     "When background analysis is allowed to run."),
        ("Analysis",      "lightbulb", "Choose OCR languages, Whisper size, and your LLM provider."),
        ("Skills",        "lightbulb", "Plugins that categorize captures into buckets."),
        ("Topics & PoIs", "lightbulb", "Track points of interest — what you want grouped + summarised."),
        ("Reports",       "document",  "How and when daily/weekly summaries are produced."),
        ("Capture",       "mic",       "Audio devices, recording details, and voice quick-notes."),
        ("Privacy",       "dismiss",   "Apps that should never be captured or analyzed."),
        ("Storage",       "folder",    "Disk retention for captures and summaries."),
        ("Data",          "save",      "Export or import your config, database, vectors, and reports."),
        ("Advanced",      "settings",  "Optional telemetry and troubleshooting controls."),
        ("Appearance",    "color",     "Theme, accent colour, and density."),
        ("About",         "info",      "Version info and update checks."),
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
            theme = current_theme(config)
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
        self._build_topics_pois_tab()
        self._build_reports_tab()
        self._build_capture_tab()
        self._build_privacy_tab()
        self._build_storage_tab()
        self._build_data_tab()
        self._build_advanced_tab()
        self._build_appearance_tab()
        self._build_about_tab()

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
        c.capture.video_backend = self._video_backend_combo.currentText().strip() or "auto"
        c.capture.draw_cursor = self._draw_cursor_check.isChecked()
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
        c.auto_check_updates = self._auto_check_updates_check.isChecked()

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
        self._video_backend_combo.setCurrentText(getattr(c.capture, "video_backend", "auto"))
        self._draw_cursor_check.setChecked(getattr(c.capture, "draw_cursor", True))
        self._sample_rate_spin.setValue(c.capture.audio_sample_rate)
        self._channels_spin.setValue(c.capture.audio_channels)
        self._quick_note_enabled.setChecked(c.capture.enable_quick_note)
        self._quick_note_seconds.setValue(c.capture.quick_note_seconds)
        self._sync_quick_note_state()

        self._telemetry_enabled.setChecked(c.telemetry.enabled)
        self._telemetry_dsn.setText(c.telemetry.dsn or "")
        self._sync_telemetry_state()
        self._auto_check_updates_check.setChecked(c.auto_check_updates)

        # Appearance tab.
        self._theme_radios[c.ui.theme].setChecked(True)
        self._accent_radios[c.ui.accent].setChecked(True)
        self._density_combo.setCurrentText(c.ui.density)

    def _on_save(self) -> None:
        if hasattr(self, "_poi_tab"):
            self._poi_tab.commit_to_config()
        self._apply_form_to_config()
        self._config.save()
        log.info("Settings saved")
        self.config_saved.emit(self._config)
        self.accept()

    # --- learn-mode glue ----------------------------------------------------------

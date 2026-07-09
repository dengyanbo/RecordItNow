"""Tab builders and tab-specific slots for the settings dialog."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import TriggerBinding
from ..utils.logging import get_logger
from ..utils.updater import UpdateInfo
from .progress import Spinner
from .settings_common import (
    _W_NUMBER,
    _W_PICKER,
    _W_TEXT,
    _W_URL,
    ACCENT_OPTIONS,
    LLM_NAMES,
    OCR_LANGUAGE_OPTIONS,
    REASONING_EFFORTS,
    REPORT_FREQUENCIES,
    THEME_MODES,
    WEEKDAY_NAMES,
    WHISPER_MODEL_HINTS,
    WHISPER_MODEL_OPTIONS,
    _AudioRefreshSignals,
    _AudioRefreshTask,
    _UpdateCheckWorker,
    _wrap,
)
from .theme import current_theme

log = get_logger(__name__)


class _SettingsTabsMixin:
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

    def _build_topics_pois_tab(self) -> None:
        from .poi_tab import TopicsAndPoIsTab

        page = TopicsAndPoIsTab(self._config)
        page.pois_changed.connect(
            self._mark_dirty if hasattr(self, "_mark_dirty") else lambda: None
        )
        self._poi_tab = page
        self._add_page(page)

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

        # --- recording backend (v1.2.0) --------------------------------------
        self._video_backend_combo = QComboBox()
        self._video_backend_combo.addItems(["auto", "ddagrab", "gdigrab"])
        self._fixed(self._video_backend_combo, _W_NUMBER)
        self._video_backend_combo.setToolTip(
            "auto: use ddagrab when available, else gdigrab.\n"
            "ddagrab: GPU-accelerated, no cursor flicker (needs a real GPU + "
            "local session; NOT available over RDP / GPU-less VMs).\n"
            "gdigrab: works everywhere, but the live cursor flickers while "
            "recording when 'Capture mouse cursor' is on."
        )
        form.addRow(self._label("Recording backend"), self._video_backend_combo)
        form.addRow(self._hint(
            "ddagrab removes the mouse-cursor flicker seen during recording. "
            "'auto' falls back to gdigrab automatically when ddagrab can't run."
        ))

        self._draw_cursor_check = QCheckBox("Capture the mouse cursor in recordings")
        self._draw_cursor_check.setToolTip(
            "On the gdigrab fallback, turning this off is the only way to stop "
            "the on-screen cursor flicker (the recording will have no cursor)."
        )
        form.addRow(self._draw_cursor_check)

        self._section_spacer(form)

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

    def _build_about_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._about_version_chip = QLabel(f"v{__version__}")
        self._about_version_chip.setProperty("role", "chip")
        self._about_version_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form.addRow(self._label("Installed version"), self._about_version_chip)

        form.addRow(self._hint(
            "RIN never auto-installs updates. The check below makes a single "
            "HTTPS request to GitHub and, if a newer release exists, shows a "
            "notification with a link to the download page."
        ))

        self._section_spacer(form)

        self._auto_check_updates_check = QCheckBox(
            "Automatically check GitHub for new releases on startup"
        )
        form.addRow(self._auto_check_updates_check)
        form.addRow(self._hint(
            "Throttled to once every 24 hours. Disable for fully offline operation."
        ))

        self._section_spacer(form)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self._check_updates_btn = QPushButton("Check for updates now")
        self._check_updates_btn.clicked.connect(self._on_check_updates_clicked)
        row.addWidget(self._check_updates_btn)
        self._check_updates_status = QLabel("")
        self._check_updates_status.setProperty("role", "field-hint")
        self._check_updates_status.setWordWrap(True)
        row.addWidget(self._check_updates_status, 1)
        form.addRow(_wrap(row))

        self._release_link = QLabel("")
        self._release_link.setOpenExternalLinks(True)
        self._release_link.linkActivated.connect(self._open_release_link)
        self._release_link.setProperty("role", "field-hint")
        self._release_link.setWordWrap(True)
        self._release_link.setVisible(False)
        form.addRow(self._release_link)

        self._add_page(page)

    @staticmethod
    def _open_release_link(url: str) -> None:
        webbrowser.open(url)

    def _on_check_updates_clicked(self) -> None:
        self._check_updates_btn.setEnabled(False)
        self._check_updates_status.setText("Checking…")
        self._release_link.setVisible(False)

        worker = _UpdateCheckWorker(force=True)
        worker.signals.finished.connect(
            self._on_check_updates_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        from . import settings_dialog

        settings_dialog.QThreadPool.globalInstance().start(worker)

    def _on_check_updates_finished(self, info: object) -> None:
        self._check_updates_btn.setEnabled(True)
        if info is None:
            self._check_updates_status.setText(
                f"You're on the latest version (v{__version__})."
            )
            self._release_link.setVisible(False)
            return
        assert isinstance(info, UpdateInfo)
        size_hint = f" (~{info.asset_size_mb:.0f} MB)" if info.asset_size_mb else ""
        self._check_updates_status.setText(
            f"RIN v{info.latest} is available{size_hint}."
        )
        self._release_link.setText(
            f'<a href="{info.html_url}">Open the release page in your browser</a>'
        )
        self._release_link.setVisible(True)

    # --- load / save --------------------------------------------------------------

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
            current_theme(self._config).accent
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

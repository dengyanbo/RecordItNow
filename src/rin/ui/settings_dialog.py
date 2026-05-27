"""Settings dialog with a left-nav layout (v0.3.0 modern UI).

The dialog uses :class:`~rin.config.RinConfig` as the source of truth.
``load_from_config`` pulls fresh values; ``Save`` validates each field,
writes the updated values back into the in-memory config, persists the
TOML file, and emits ``config_saved`` so listeners (tray, input manager,
theme manager) can react.

Layout: a 200 px ``QListWidget`` on the left acts as a navigation rail
(``role="nav"`` for stylesheet pickup); the right pane is a
``QStackedWidget`` with one page per section. The dialog is wider than
v0.1's tabbed layout to make every form less cramped.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import RinConfig, TriggerBinding
from ..utils.logging import get_logger

log = get_logger(__name__)

LLM_NAMES = ["copilot_cli", "openai", "azure", "none"]
REPORT_FREQUENCIES = ["daily", "weekly", "off"]
REASONING_EFFORTS = ["", "none", "low", "medium", "high", "xhigh", "max"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
THEME_MODES = ["auto", "light", "dark"]
ACCENT_OPTIONS = ["blue", "purple", "teal", "orange"]


def _nav_icon(name: str) -> QIcon:
    """Return a Fluent SVG icon for the nav rail, or empty QIcon if missing."""

    try:
        from . import icon_path

        return QIcon(str(icon_path(name)))
    except (FileNotFoundError, ImportError):
        return QIcon()


class SettingsDialog(QDialog):
    config_saved = Signal(RinConfig)

    NAV_ITEMS = (
        ("Trigger",       "keyboard"),
        ("Working hours", "clock"),
        ("Analysis",      "lightbulb"),
        ("Reports",       "document"),
        ("Capture",       "mic"),
        ("Storage",       "folder"),
        ("Appearance",    "color"),
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
        self.setMinimumSize(720, 540)
        self._config = config
        self._learn_callback = learn_callback

        self._nav = QListWidget()
        self._nav.setProperty("role", "nav")
        self._nav.setFixedWidth(190)
        self._nav.setIconSize(QSize(16, 16))
        self._nav.setSpacing(0)
        self._nav.setFrameShape(QFrame.Shape.NoFrame)
        for label, icon_name in self.NAV_ITEMS:
            item = QListWidgetItem(_nav_icon(icon_name), "  " + label)
            self._nav.addItem(item)

        self._stack = QStackedWidget()
        self._build_trigger_tab()
        self._build_working_hours_tab()
        self._build_llm_tab()
        self._build_reports_tab()
        self._build_capture_tab()
        self._build_storage_tab()
        self._build_appearance_tab()

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        save_btn = QPushButton("Save")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
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

        Pulls the heading text from the latest nav item just inserted (the
        order of build calls matches ``NAV_ITEMS``).
        """

        idx = self._stack.count()
        title = self.NAV_ITEMS[idx][0] if idx < len(self.NAV_ITEMS) else ""

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        wrapper = QWidget()
        col = QVBoxLayout(wrapper)
        col.setContentsMargins(28, 24, 28, 16)
        col.setSpacing(16)

        if title:
            heading = QLabel(title)
            heading.setProperty("heading", "h1")
            col.addWidget(heading)

        col.addWidget(page)
        col.addStretch()
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
        form.setVerticalSpacing(14)
        form.setContentsMargins(0, 0, 0, 0)
        return form

    @staticmethod
    def _heading(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("heading", "h2")
        return lbl

    @staticmethod
    def _label(text: str) -> QLabel:
        """Field label (small muted caption above its input)."""

        lbl = QLabel(text)
        lbl.setProperty("role", "field-label")
        return lbl

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "caption")
        lbl.setWordWrap(True)
        return lbl

    # --- tab builders -------------------------------------------------------------

    def _build_trigger_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._binding_label = QLabel("(unset)")
        self._binding_label.setObjectName("trigger_label")
        self._learn_button = QPushButton("Learn new button…")
        self._learn_button.clicked.connect(self._on_learn_clicked)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._binding_label, 1)
        row.addWidget(self._learn_button, 0)
        form.addRow(self._label("Trigger button"), _wrap(row))

        self._hold_spin = QSpinBox()
        self._hold_spin.setRange(100, 5000)
        self._hold_spin.setSingleStep(50)
        self._hold_spin.setSuffix(" ms")
        self._hold_spin.setMaximumWidth(180)
        form.addRow(self._label("Hold threshold"), self._hold_spin)
        form.addRow(self._hint(
            "Tap the trigger to take a screenshot; hold past this threshold "
            "to start recording video. Release to stop."
        ))

        self._add_page(page)

    def _build_working_hours_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._wh_enabled = QCheckBox("Apply working-hours gate to hourly analysis")
        form.addRow(self._wh_enabled)

        self._wh_start = QSpinBox()
        self._wh_start.setRange(0, 23)
        self._wh_start.setSuffix(" h")
        self._wh_start.setMaximumWidth(110)
        self._wh_end = QSpinBox()
        self._wh_end.setRange(0, 23)
        self._wh_end.setSuffix(" h")
        self._wh_end.setMaximumWidth(110)
        hours_row = QHBoxLayout()
        hours_row.setSpacing(6)
        from_lbl = QLabel("From")
        from_lbl.setProperty("muted", True)
        to_lbl = QLabel("to")
        to_lbl.setProperty("muted", True)
        hours_row.addWidget(from_lbl)
        hours_row.addWidget(self._wh_start)
        hours_row.addWidget(to_lbl)
        hours_row.addWidget(self._wh_end)
        hours_row.addStretch()
        form.addRow(self._label("Hours"), _wrap(hours_row))

        self._weekday_checks: list[QCheckBox] = []
        wd_row = QHBoxLayout()
        wd_row.setSpacing(4)
        for label in WEEKDAY_NAMES:
            cb = QCheckBox(label)
            self._weekday_checks.append(cb)
            wd_row.addWidget(cb)
        wd_row.addStretch()
        form.addRow(self._label("Workdays"), _wrap(wd_row))

        self._idle_minutes = QSpinBox()
        self._idle_minutes.setRange(1, 240)
        self._idle_minutes.setSuffix(" min")
        self._idle_minutes.setMaximumWidth(140)
        form.addRow(self._label("Idle threshold"), self._idle_minutes)

        self._add_page(page)

    def _build_llm_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._llm_combo = QComboBox()
        self._llm_combo.addItems(LLM_NAMES)
        self._llm_combo.setMaximumWidth(220)
        form.addRow(self._label("Provider"), self._llm_combo)

        self._llm_model = QLineEdit()
        self._llm_model.setPlaceholderText("Provider default (leave blank)")
        self._llm_model.setMaximumWidth(360)
        form.addRow(self._label("Model"), self._llm_model)

        self._effort_combo = QComboBox()
        self._effort_combo.addItems(REASONING_EFFORTS)
        self._effort_combo.setMaximumWidth(220)
        self._effort_combo.setToolTip(
            "Copilot CLI only — reasoning effort. Leave blank to use the model's default."
        )
        form.addRow(self._label("Reasoning effort"), self._effort_combo)

        self._azure_endpoint = QLineEdit()
        self._azure_endpoint.setPlaceholderText("https://your-resource.openai.azure.com")
        self._azure_endpoint.setMaximumWidth(420)
        form.addRow(self._label("Azure endpoint"), self._azure_endpoint)

        self._azure_deployment = QLineEdit()
        self._azure_deployment.setMaximumWidth(360)
        form.addRow(self._label("Azure deployment"), self._azure_deployment)

        self._llm_timeout = QSpinBox()
        self._llm_timeout.setRange(5, 600)
        self._llm_timeout.setSuffix(" s")
        self._llm_timeout.setMaximumWidth(140)
        form.addRow(self._label("Request timeout"), self._llm_timeout)

        self._hourly_enabled = QCheckBox("Run hourly auto-analysis")
        form.addRow(self._hourly_enabled)
        self._require_idle = QCheckBox(
            "Only analyze outside working hours OR when idle"
        )
        form.addRow(self._require_idle)

        self._add_page(page)

    def _build_reports_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._report_combo = QComboBox()
        self._report_combo.addItems(REPORT_FREQUENCIES)
        self._report_combo.setMaximumWidth(220)
        form.addRow(self._label("Frequency"), self._report_combo)

        self._notify_check = QCheckBox("Show a notification when a report is ready")
        form.addRow(self._notify_check)

        self._add_page(page)

    def _build_storage_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(1, 3650)
        self._retention_spin.setSuffix(" days")
        self._retention_spin.setMaximumWidth(160)
        form.addRow(self._label("Keep raw captures for"), self._retention_spin)

        self._keep_summaries = QCheckBox("Keep AI summaries forever")
        form.addRow(self._keep_summaries)

        self._min_space = QSpinBox()
        self._min_space.setRange(1, 1000)
        self._min_space.setSuffix(" GB")
        self._min_space.setMaximumWidth(140)
        form.addRow(self._label("Minimum free space"), self._min_space)

        self._add_page(page)

    def _build_capture_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._audio_combo = QComboBox()
        self._audio_combo.setEditable(True)
        self._audio_combo.setMaximumWidth(420)
        self._audio_combo.setToolTip(
            "DirectShow audio device to mix into video recordings. "
            "Leave blank to record video only."
        )
        self._refresh_audio_button = QPushButton("Refresh devices")
        self._refresh_audio_button.clicked.connect(self._refresh_audio_devices)
        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        audio_row.addWidget(self._audio_combo, 1)
        audio_row.addWidget(self._refresh_audio_button, 0)
        form.addRow(self._label("Audio device"), _wrap(audio_row))
        form.addRow(self._hint(
            "Enable 'Stereo Mix' in Windows Sound settings to capture "
            "system audio (not just the mic)."
        ))

        self._sample_rate_spin = QSpinBox()
        self._sample_rate_spin.setRange(8000, 192000)
        self._sample_rate_spin.setSingleStep(1000)
        self._sample_rate_spin.setSuffix(" Hz")
        self._sample_rate_spin.setMaximumWidth(160)
        form.addRow(self._label("Sample rate"), self._sample_rate_spin)

        self._channels_spin = QSpinBox()
        self._channels_spin.setRange(1, 8)
        self._channels_spin.setMaximumWidth(100)
        form.addRow(self._label("Audio channels"), self._channels_spin)

        self._tabs_addTab_legacy_marker = None  # replaced below
        self._add_page(page)

    def _build_appearance_tab(self) -> None:
        page = QWidget()
        form = self._form()
        page.setLayout(form)

        self._theme_group = QButtonGroup(self)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(16)
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
        accent_row.setSpacing(16)
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
        self._density_combo.setMaximumWidth(220)
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

        self._report_combo.setCurrentText(c.reports.frequency)
        self._notify_check.setChecked(c.reports.deliver_via_notification)

        self._retention_spin.setValue(c.storage.raw_retention_days)
        self._keep_summaries.setChecked(c.storage.keep_summaries_forever)
        self._min_space.setValue(c.storage.min_free_space_gb)

        # Capture tab — populate audio device list (best effort), preselect current.
        self._populate_audio_combo(initial=c.capture.audio_device or "")
        self._sample_rate_spin.setValue(c.capture.audio_sample_rate)
        self._channels_spin.setValue(c.capture.audio_channels)

        # Appearance tab.
        self._theme_radios[c.ui.theme].setChecked(True)
        self._accent_radios[c.ui.accent].setChecked(True)
        self._density_combo.setCurrentText(c.ui.density)

    def _on_save(self) -> None:
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

        c.reports.frequency = self._report_combo.currentText()
        c.reports.deliver_via_notification = self._notify_check.isChecked()

        c.storage.raw_retention_days = self._retention_spin.value()
        c.storage.keep_summaries_forever = self._keep_summaries.isChecked()
        c.storage.min_free_space_gb = self._min_space.value()

        c.capture.audio_device = self._audio_combo.currentText().strip() or None
        c.capture.audio_sample_rate = self._sample_rate_spin.value()
        c.capture.audio_channels = self._channels_spin.value()

        for mode, rb in self._theme_radios.items():
            if rb.isChecked():
                c.ui.theme = mode  # type: ignore[assignment]
                break
        for accent, rb in self._accent_radios.items():
            if rb.isChecked():
                c.ui.accent = accent  # type: ignore[assignment]
                break
        c.ui.density = self._density_combo.currentText()  # type: ignore[assignment]

        c.save()
        log.info("Settings saved")
        self.config_saved.emit(c)
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
        if binding.source == "unset":
            return "(unset — click 'Learn new button')"
        if binding.label:
            return binding.label
        if binding.source == "keyboard":
            return f"Key: {binding.key}"
        if binding.source == "mouse":
            return f"Mouse: {binding.key}"
        return f"HID {binding.vendor_id:#06x}:{binding.product_id:#06x}"

    # --- audio device picker ------------------------------------------------------

    def _populate_audio_combo(self, *, initial: str = "") -> None:
        from ..capture import list_dshow_audio_devices

        self._audio_combo.blockSignals(True)
        self._audio_combo.clear()
        # Always offer a blank "no audio" choice as the first entry.
        self._audio_combo.addItem("")
        try:
            for name in list_dshow_audio_devices():
                self._audio_combo.addItem(name)
        except Exception as exc:
            log.warning(f"Audio device enumeration failed: {exc}")
        # Make sure the configured device is selectable even if enumeration missed it.
        if initial and self._audio_combo.findText(initial) == -1:
            self._audio_combo.addItem(initial)
        self._audio_combo.setCurrentText(initial)
        self._audio_combo.blockSignals(False)

    def _refresh_audio_devices(self) -> None:
        current = self._audio_combo.currentText().strip()
        self._populate_audio_combo(initial=current)


def _wrap(layout) -> QWidget:
    """Wrap a layout in a transparent ``QWidget`` so it can sit in a ``QFormLayout``."""

    w = QWidget()
    w.setLayout(layout)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return w

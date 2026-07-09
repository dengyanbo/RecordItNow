"""First-run onboarding wizard."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..config import RinConfig, TriggerBinding
from ..utils.logging import get_logger
from .icon import tinted_icon
from .style import palette_to_qss
from .theme import current_theme

log = get_logger(__name__)

LLM_NAMES = ["copilot_cli", "openai", "azure", "none"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class FirstRunWizard(QWizard):
    """Guide a new install through the minimum setup needed to start capturing."""

    def __init__(
        self,
        cfg: RinConfig,
        *,
        learn_callback: Callable[[Callable[[TriggerBinding], None]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = cfg
        self._learn_callback = learn_callback
        self.setWindowTitle("Welcome to RIN")
        self.setMinimumSize(720, 520)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        theme = current_theme(cfg)
        self.setStyleSheet(palette_to_qss(theme, density=cfg.ui.density))
        self._accent = theme.accent

        self._welcome_page = _InfoPage(
            icon_name="camera",
            accent=self._accent,
            title="Capture your day, then search it later.",
            body=(
                "This quick setup gets RIN ready with a trigger button, your preferred "
                "LLM provider, and working hours for automatic analysis."
            ),
        )
        self._trigger_page = _TriggerPage(cfg, self._accent, learn_callback=learn_callback)
        self._provider_page = _ProviderPage(cfg, self._accent)
        self._hours_page = _WorkingHoursPage(cfg, self._accent)
        self._done_page = _DonePage(cfg, self._accent)

        self.setPage(0, self._welcome_page)
        self.setPage(1, self._trigger_page)
        self.setPage(2, self._provider_page)
        self.setPage(3, self._hours_page)
        self.setPage(4, self._done_page)
        self.setStartId(0)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Finish")

    def accept(self) -> None:
        self._config.trigger = self._trigger_page.binding
        self._config.llm.name = self._provider_page.provider_name
        self._config.working_hours.enabled = self._hours_page.enabled
        self._config.working_hours.start_hour = self._hours_page.start_hour
        self._config.working_hours.end_hour = self._hours_page.end_hour
        self._config.working_hours.weekdays = self._hours_page.weekdays
        self._config.first_run_completed = True
        self._config.save()
        log.info("First-run wizard completed")
        super().accept()


class _HeaderPage(QWizardPage):
    def __init__(self, *, icon_name: str, accent: str, title: str, body: str) -> None:
        super().__init__()
        self.setTitle("")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(16)
        outer.addWidget(_header(icon_name, accent, title, body))
        self._body_layout = QVBoxLayout()
        self._body_layout.setSpacing(12)
        outer.addLayout(self._body_layout)
        outer.addStretch(1)


class _InfoPage(_HeaderPage):
    def __init__(self, *, icon_name: str, accent: str, title: str, body: str) -> None:
        super().__init__(icon_name=icon_name, accent=accent, title=title, body=body)
        hint = QLabel(
            "You can revisit every option later from the tray icon → Settings."
        )
        hint.setProperty("role", "field-hint")
        hint.setWordWrap(True)
        self._body_layout.addWidget(hint)


class _TriggerPage(_HeaderPage):
    def __init__(
        self,
        cfg: RinConfig,
        accent: str,
        *,
        learn_callback: Callable[[Callable[[TriggerBinding], None]], None] | None,
    ) -> None:
        super().__init__(
            icon_name="keyboard",
            accent=accent,
            title="Choose the button that starts every capture.",
            body=(
                "Tap it for a screenshot. Hold it to start a recording, then release to stop."
            ),
        )
        self._learn_callback = learn_callback
        self.binding = cfg.trigger

        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._binding_label = QLabel(_format_binding(self.binding))
        self._binding_label.setProperty("role", "chip")
        self._binding_label.setProperty("accent", True)
        self._binding_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._binding_label.setMinimumHeight(30)
        layout.addWidget(self._binding_label, 0, Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel(
            "Press “Learn new button…” and then tap the key, mouse button, or HID button you want to use."
        )
        self._status.setProperty("role", "field-hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._learn_button = QPushButton("Learn new button…")
        self._learn_button.setProperty("primary", True)
        self._learn_button.clicked.connect(self._on_learn_clicked)
        layout.addWidget(self._learn_button, 0, Qt.AlignmentFlag.AlignLeft)

        if self._learn_callback is None:
            self._status.setText(
                "Learn mode is unavailable in this session. You can finish now and set a trigger later in Settings."
            )

        self._body_layout.addWidget(card)

    def isComplete(self) -> bool:
        return self.binding.source != "unset" or self._learn_callback is None

    def _on_learn_clicked(self) -> None:
        if self._learn_callback is None:
            return
        self._binding_label.setText("Press any button…")
        self._status.setText("Listening for the next input event…")
        self._learn_button.setEnabled(False)
        self._learn_callback(self._on_binding_learned)

    def _on_binding_learned(self, binding: TriggerBinding) -> None:
        self.binding = binding
        self._binding_label.setText(_format_binding(binding))
        self._status.setText("Trigger captured. Click Next to continue.")
        self._learn_button.setEnabled(True)
        self.completeChanged.emit()


class _ProviderPage(_HeaderPage):
    def __init__(self, cfg: RinConfig, accent: str) -> None:
        super().__init__(
            icon_name="chat",
            accent=accent,
            title="Pick the LLM provider RIN should use for summaries.",
            body="Copilot CLI is the default and works without storing API keys in config.toml.",
        )
        self._combo = QComboBox()
        self._combo.addItems(LLM_NAMES)
        self._combo.setFixedWidth(240)
        self._combo.setCurrentText(cfg.llm.name)
        self._body_layout.addWidget(_labeled("Provider", self._combo))

    @property
    def provider_name(self) -> str:
        return self._combo.currentText()


class _WorkingHoursPage(_HeaderPage):
    def __init__(self, cfg: RinConfig, accent: str) -> None:
        super().__init__(
            icon_name="clock",
            accent=accent,
            title="Tell RIN when background analysis is allowed to run.",
            body="These hours gate the automatic hourly analysis pass.",
        )

        self._enabled = QCheckBox("Apply working-hours gate to hourly analysis")
        self._enabled.setChecked(cfg.working_hours.enabled)
        self._body_layout.addWidget(self._enabled)

        hours_row = QHBoxLayout()
        hours_row.setContentsMargins(0, 0, 0, 0)
        hours_row.setSpacing(8)
        self._start = QSpinBox()
        self._start.setRange(0, 23)
        self._start.setSuffix(" h")
        self._start.setValue(cfg.working_hours.start_hour)
        self._end = QSpinBox()
        self._end.setRange(0, 23)
        self._end.setSuffix(" h")
        self._end.setValue(cfg.working_hours.end_hour)
        hours_row.addWidget(QLabel("From"))
        hours_row.addWidget(self._start)
        hours_row.addWidget(QLabel("to"))
        hours_row.addWidget(self._end)
        hours_row.addStretch(1)
        self._body_layout.addWidget(_labeled("Hours", _wrap(hours_row)))

        days_row = QHBoxLayout()
        days_row.setContentsMargins(0, 0, 0, 0)
        days_row.setSpacing(8)
        active = set(cfg.working_hours.weekdays)
        self._weekday_checks: list[QCheckBox] = []
        for index, label in enumerate(WEEKDAY_NAMES):
            cb = QCheckBox(label)
            cb.setChecked(index in active)
            self._weekday_checks.append(cb)
            days_row.addWidget(cb)
        days_row.addStretch(1)
        self._body_layout.addWidget(_labeled("Workdays", _wrap(days_row)))

    @property
    def enabled(self) -> bool:
        return self._enabled.isChecked()

    @property
    def start_hour(self) -> int:
        return self._start.value()

    @property
    def end_hour(self) -> int:
        return self._end.value()

    @property
    def weekdays(self) -> list[int]:
        return [index for index, cb in enumerate(self._weekday_checks) if cb.isChecked()]


class _DonePage(_HeaderPage):
    def __init__(self, cfg: RinConfig, accent: str) -> None:
        super().__init__(
            icon_name="checkmark",
            accent=accent,
            title="You’re ready to start capturing.",
            body="Finish to save your setup and start RIN in the system tray.",
        )
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setProperty("role", "field-hint")
        self._body_layout.addWidget(self._summary)
        self._cfg = cfg

    def initializePage(self) -> None:
        wizard = self.wizard()
        trigger_page = wizard.page(1)
        provider_page = wizard.page(2)
        hours_page = wizard.page(3)
        assert isinstance(trigger_page, _TriggerPage)
        assert isinstance(provider_page, _ProviderPage)
        assert isinstance(hours_page, _WorkingHoursPage)
        weekdays = ", ".join(
            WEEKDAY_NAMES[index] for index in hours_page.weekdays
        ) or "No days selected"
        self._summary.setText(
            "\n".join(
                [
                    f"Trigger: {_format_binding(trigger_page.binding)}",
                    f"LLM provider: {provider_page.provider_name}",
                    (
                        f"Working hours: {'On' if hours_page.enabled else 'Off'}"
                        f" — {hours_page.start_hour}:00 to {hours_page.end_hour}:00 ({weekdays})"
                    ),
                ]
            )
        )
        super().initializePage()


def _header(icon_name: str, accent: str, title: str, body: str) -> QWidget:
    widget = QWidget()
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(tinted_icon(icon_name, accent, sizes=(32,)).pixmap(QSize(32, 32)))
    icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
    row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(6)
    heading = QLabel(title)
    heading.setProperty("heading", "h1")
    body_label = QLabel(body)
    body_label.setProperty("role", "caption")
    body_label.setWordWrap(True)
    text_col.addWidget(heading)
    text_col.addWidget(body_label)
    row.addLayout(text_col, 1)
    return widget


def _labeled(label: str, widget: QWidget) -> QWidget:
    wrapper = QWidget()
    col = QVBoxLayout(wrapper)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(6)
    title = QLabel(label)
    title.setProperty("role", "field-label")
    col.addWidget(title)
    col.addWidget(widget)
    return wrapper


def _wrap(layout: QHBoxLayout) -> QWidget:
    wrapper = QWidget()
    wrapper.setLayout(layout)
    return wrapper


def _format_binding(binding: TriggerBinding) -> str:
    if binding.source == "unset":
        return "Not set"
    if binding.source == "keyboard" and binding.key:
        return binding.key.upper()
    if binding.source == "mouse" and binding.key:
        return f"Mouse · {binding.key}"
    if binding.source == "hid":
        return f"HID {binding.vendor_id:#06x}:{binding.product_id:#06x}"
    return binding.label or binding.source

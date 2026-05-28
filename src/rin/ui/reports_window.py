"""Reports browser window — v0.4.2 async polish.

Left rail: card-styled list of saved reports (date, kind chip,
file name). Right pane: rendered Markdown via ``QTextBrowser`` with
theme-aware styling. Action row beneath the list keeps the generate +
refresh actions visually attached to the listing.

Long-running operations (LLM-driven report generation) run on a
:class:`QThreadPool` worker so the Qt main thread never blocks. A
:class:`BusyOverlay` is raised over the viewer pane while a generation
is in flight, and the side-rail buttons disable themselves until the
worker signals completion.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ..config import RinConfig
from ..reports import generate_report, weekly_period
from ..reports.generator import daily_period
from ..storage import session
from ..storage.models import Report
from ..utils.logging import get_logger
from .icon import tinted_icon
from .progress import BusyOverlay
from .theme import LIGHT, Theme, resolve, with_accent

log = get_logger(__name__)


class _ReportSignals(QObject):
    done = Signal(object)         # (ReportResult)
    failed = Signal(str)           # error message


class _GenerateReportTask(QRunnable):
    """Run :func:`generate_report` on a worker thread."""

    def __init__(self, kind: str, config: RinConfig, signals: _ReportSignals) -> None:
        super().__init__()
        self._kind = kind
        self._config = config
        self._signals = signals

    def run(self) -> None:  # pragma: no cover - thread plumbing
        try:
            period = daily_period() if self._kind == "daily" else weekly_period()
            result = generate_report(period, self._config)
            self._signals.done.emit(result)
        except Exception as exc:
            log.exception(f"Report generation failed: {exc}")
            self._signals.failed.emit(str(exc))


def _md_to_html(text: str, theme: Theme) -> str:
    """Render markdown to a themed HTML snippet for QTextBrowser."""

    try:
        import markdown
        body = markdown.markdown(text, extensions=["fenced_code", "tables"])
    except ImportError:
        body = "<pre>" + text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
    return f"""
<style>
  body {{
    font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
    color: {theme.text};
    background: transparent;
    line-height: 1.55;
  }}
  h1, h2, h3, h4 {{ color: {theme.text}; margin-top: 18px; }}
  h1 {{ font-size: 22px; }}
  h2 {{ font-size: 18px; border-bottom: 1px solid {theme.border}; padding-bottom: 4px; }}
  h3 {{ font-size: 15px; color: {theme.text_muted}; }}
  blockquote {{
    border-left: 3px solid {theme.accent};
    margin-left: 0; padding-left: 12px;
    color: {theme.text_muted};
  }}
  code {{
    background: {theme.surface_alt};
    border: 1px solid {theme.border};
    border-radius: 4px;
    padding: 1px 5px;
    font-family: Consolas, 'Cascadia Code', monospace;
  }}
  pre code {{ border: none; padding: 0; }}
  pre {{
    background: {theme.surface_alt};
    border: 1px solid {theme.border};
    border-radius: 6px;
    padding: 10px;
    overflow-x: auto;
  }}
  a {{ color: {theme.accent}; text-decoration: none; }}
  table {{ border-collapse: collapse; margin: 8px 0; }}
  th, td {{ border: 1px solid {theme.border}; padding: 4px 8px; }}
  th {{ background: {theme.surface_alt}; }}
</style>
<div>{body}</div>
"""


class _EmptyState(QWidget):
    """Centered placeholder shown when there's nothing to display.

    Renders a tinted SVG icon above the heading + supporting text so the
    state looks intentional rather than "we forgot to load something".
    """

    def __init__(
        self,
        title: str,
        hint: str,
        *,
        icon_name: str = "info",
        icon_color: str = "#9E9E9E",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(10)
        layout.addStretch()

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(
            tinted_icon(icon_name, icon_color, sizes=(48,)).pixmap(QSize(48, 48))
        )
        layout.addWidget(icon_label)

        title_lbl = QLabel(title)
        title_lbl.setProperty("role", "empty-state-title")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl = QLabel(hint)
        hint_lbl.setProperty("role", "empty-state-hint")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setWordWrap(True)
        hint_lbl.setMinimumHeight(48)
        layout.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(hint_lbl)
        layout.addStretch()


class _ReportCard(QWidget):
    """A single report card in the left list — single-line meta + filename."""

    def __init__(self, report: Report, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report

        kind_text = {"daily": "Daily", "weekly": "Weekly"}.get(report.kind, report.kind)
        date_label = QLabel(report.period_start.strftime("%b %d, %Y"))
        date_label.setStyleSheet("font-weight: 600;")
        kind_chip = QLabel(kind_text)
        kind_chip.setProperty("role", "chip")
        kind_chip.setProperty("accent", report.kind == "weekly")
        kind_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kind_chip.setMinimumHeight(20)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.addWidget(date_label, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addStretch()
        top_row.addWidget(kind_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        path_label = QLabel(Path(report.markdown_path).name)
        path_label.setProperty("role", "caption")

        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(4)
        col.addLayout(top_row)
        col.addWidget(path_label)


class ReportsWindow(QWidget):
    def __init__(self, config: RinConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("RIN — Reports")
        self.resize(1080, 680)

        self._pool = QThreadPool.globalInstance()
        self._signals = _ReportSignals()
        self._signals.done.connect(self._on_report_done)
        self._signals.failed.connect(self._on_report_failed)

        self._list = QListWidget()
        self._list.setProperty("role", "cards")
        self._list.setIconSize(QSize(0, 0))
        self._list.setSpacing(0)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setFrameShape(QFrame.Shape.NoFrame)

        self._viewer = QTextBrowser()
        self._viewer.setOpenExternalLinks(True)
        self._viewer.setFrameShape(QFrame.Shape.NoFrame)

        # Empty state for the right pane.
        self._empty_state = _EmptyState(
            "Select a report",
            "Pick a report on the left, or generate today's report to get started.",
            icon_name="document",
        )
        self._viewer_stack = QStackedWidget()
        self._viewer_stack.addWidget(self._empty_state)
        self._viewer_stack.addWidget(self._viewer)

        # Busy overlay floats above the viewer stack — not part of any
        # layout so it can resize to cover its parent at show() time.
        self._busy_host = QWidget()
        host_layout = QVBoxLayout(self._busy_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addWidget(self._viewer_stack)
        self._busy = BusyOverlay(
            self._busy_host,
            message="Generating report…",
            theme=self._theme(),
        )

        self._gen_today_btn = QPushButton("Today")
        self._gen_today_btn.setProperty("primary", True)
        self._gen_today_btn.clicked.connect(self._generate_today)
        self._gen_week_btn = QPushButton("This week")
        self._gen_week_btn.clicked.connect(self._generate_week)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setProperty("flat", True)
        self._refresh_btn.clicked.connect(self._refresh_list)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        gen_label = QLabel("Generate")
        gen_label.setProperty("heading", "subtle")
        action_row.addWidget(gen_label, 0, Qt.AlignmentFlag.AlignVCenter)
        action_row.addWidget(self._gen_today_btn)
        action_row.addWidget(self._gen_week_btn)
        action_row.addStretch()
        action_row.addWidget(self._refresh_btn)

        side = QVBoxLayout()
        side.setContentsMargins(24, 24, 16, 24)
        side.setSpacing(10)
        heading = QLabel("Reports")
        heading.setProperty("heading", "h1")
        side.addWidget(heading)
        subtitle = QLabel("Daily and weekly summaries of your captures.")
        subtitle.setProperty("role", "caption")
        subtitle.setWordWrap(True)
        side.addWidget(subtitle)
        side.addSpacing(8)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        list_caption = QLabel("Saved reports")
        list_caption.setProperty("heading", "subtle")
        count_chip = QLabel("0")
        count_chip.setProperty("role", "chip")
        count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_chip.setMinimumWidth(28)
        meta_row.addWidget(list_caption)
        meta_row.addStretch()
        meta_row.addWidget(count_chip)
        side.addLayout(meta_row)
        self._list_caption = count_chip

        side.addWidget(self._list, 1)
        side.addLayout(action_row)

        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(320)

        divider = QFrame()
        divider.setProperty("role", "divider-vert")
        divider.setFixedWidth(1)

        viewer_col = QVBoxLayout()
        viewer_col.setContentsMargins(24, 24, 24, 24)
        viewer_col.addWidget(self._busy_host)

        viewer_widget = QWidget()
        viewer_widget.setLayout(viewer_col)

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(side_widget)
        main.addWidget(divider)
        main.addWidget(viewer_widget, 1)

        self._refresh_list()

    # --- slots --------------------------------------------------------------------

    def _all_reports(self):
        with session() as s:
            return s.scalars(select(Report).order_by(Report.period_start.desc())).all()

    def _theme(self) -> Theme:
        try:
            return with_accent(resolve(self.config.ui.theme), self.config.ui.accent)
        except Exception:
            return LIGHT

    def _refresh_list(self) -> None:
        self._list.clear()
        rows = self._all_reports()
        self._list_caption.setText(str(len(rows)))
        if not rows:
            empty_item = QListWidgetItem("No reports yet — click Generate today.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty_item)
            return
        for r in rows:
            card = _ReportCard(r)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, r.markdown_path)
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            self._viewer.setPlainText(f"Could not open {path}: {exc}")
            self._viewer_stack.setCurrentWidget(self._viewer)
            return
        self._viewer.setHtml(_md_to_html(text, self._theme()))
        self._viewer_stack.setCurrentWidget(self._viewer)

    # --- generation (async) -------------------------------------------------------

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self._gen_today_btn, self._gen_week_btn, self._refresh_btn):
            btn.setEnabled(enabled)

    def _start_generation(self, kind: str, label: str) -> None:
        """Kick off a report-generation worker and raise the busy overlay."""

        if not self._busy.isHidden():
            # Already running — ignore re-clicks (also defensive: buttons
            # are disabled, but a hotkey could still arrive).
            return
        self._busy.set_theme(self._theme())
        self._busy.set_message(f"Generating {label} report…")
        self._busy.show()
        self._set_actions_enabled(False)
        self._pool.start(_GenerateReportTask(kind, self.config, self._signals))

    def _generate_today(self) -> None:
        self._start_generation("daily", "today's")

    def _generate_week(self) -> None:
        self._start_generation("weekly", "this week's")

    def _on_report_done(self, result) -> None:
        self._busy.hide()
        self._set_actions_enabled(True)
        try:
            body = result.body
        except AttributeError:
            body = str(result)
        self._viewer.setHtml(_md_to_html(body, self._theme()))
        self._viewer_stack.setCurrentWidget(self._viewer)
        self._refresh_list()

    def _on_report_failed(self, msg: str) -> None:
        self._busy.hide()
        self._set_actions_enabled(True)
        self._viewer.setPlainText(
            f"Report generation failed:\n\n{msg}\n\n"
            "Check rin.log for details, or run Tray → Generate diagnostic report."
        )
        self._viewer_stack.setCurrentWidget(self._viewer)

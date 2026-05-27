"""Reports browser window — v0.3.0 Fluent-inspired redesign.

Left rail: card-styled list of saved reports (date, kind, capture count,
preview snippet). Right pane: rendered Markdown via ``QTextBrowser``
with theme-aware styling.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
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
from .theme import LIGHT, Theme, resolve, with_accent

log = get_logger(__name__)


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
    """Centered placeholder shown when there's nothing to display."""

    def __init__(self, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(8)
        layout.addStretch()
        title_lbl = QLabel(title)
        title_lbl.setProperty("role", "empty-state-title")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl = QLabel(hint)
        hint_lbl.setProperty("role", "empty-state-hint")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)
        layout.addWidget(hint_lbl)
        layout.addStretch()


class _ReportCard(QWidget):
    """A single report card in the left list — compact two-line layout."""

    def __init__(self, report: Report, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report

        kind_text = {"daily": "Daily", "weekly": "Weekly"}.get(report.kind, report.kind)
        date_label = QLabel(report.period_start.strftime("%Y-%m-%d"))
        date_label.setStyleSheet("font-weight: 600;")
        kind_label = QLabel(f"  ·  {kind_text}")
        kind_label.setProperty("muted", True)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)
        top_row.addWidget(date_label)
        top_row.addWidget(kind_label)
        top_row.addStretch()

        path_label = QLabel(Path(report.markdown_path).name)
        path_label.setProperty("role", "caption")

        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(2)
        col.addLayout(top_row)
        col.addWidget(path_label)


class ReportsWindow(QWidget):
    def __init__(self, config: RinConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("RIN — Reports")
        self.resize(1020, 640)

        self._list = QListWidget()
        self._list.setProperty("role", "cards")
        self._list.setIconSize(QSize(0, 0))
        self._list.setSpacing(2)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setFrameShape(QFrame.Shape.NoFrame)

        self._viewer = QTextBrowser()
        self._viewer.setOpenExternalLinks(True)
        self._viewer.setFrameShape(QFrame.Shape.NoFrame)

        # Empty state for the right pane.
        self._empty_state = _EmptyState(
            "Select a report",
            "Pick a report on the left, or generate today's report to get started.",
        )
        self._viewer_stack = QStackedWidget()
        self._viewer_stack.addWidget(self._empty_state)
        self._viewer_stack.addWidget(self._viewer)

        gen_today = QPushButton("Generate today's report")
        gen_today.setProperty("primary", True)
        gen_today.clicked.connect(self._generate_today)
        gen_week = QPushButton("Generate weekly report")
        gen_week.clicked.connect(self._generate_week)
        refresh = QPushButton("Refresh")
        refresh.setProperty("flat", True)
        refresh.clicked.connect(self._refresh_list)

        side = QVBoxLayout()
        side.setContentsMargins(20, 20, 12, 20)
        side.setSpacing(12)
        heading = QLabel("Reports")
        heading.setProperty("heading", "h1")
        side.addWidget(heading)
        list_caption = QLabel(f"Saved · {len(self._all_reports())}")
        list_caption.setProperty("role", "caption")
        side.addWidget(list_caption)
        self._list_caption = list_caption
        side.addWidget(self._list, 1)
        side.addWidget(gen_today)
        side.addWidget(gen_week)
        side.addWidget(refresh)

        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(320)

        viewer_col = QVBoxLayout()
        viewer_col.setContentsMargins(20, 20, 20, 20)
        viewer_col.addWidget(self._viewer_stack)

        viewer_widget = QWidget()
        viewer_widget.setLayout(viewer_col)

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(side_widget)
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
        self._list_caption.setText(f"Saved · {len(rows)}")
        if not rows:
            placeholder = QListWidgetItem("Nothing saved yet")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
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

    def _generate_today(self) -> None:
        self._viewer.setPlainText("Generating today's report…")
        self._viewer_stack.setCurrentWidget(self._viewer)
        result = generate_report(daily_period(), self.config)
        self._viewer.setHtml(_md_to_html(result.body, self._theme()))
        self._refresh_list()

    def _generate_week(self) -> None:
        self._viewer.setPlainText("Generating weekly report…")
        self._viewer_stack.setCurrentWidget(self._viewer)
        result = generate_report(weekly_period(), self.config)
        self._viewer.setHtml(_md_to_html(result.body, self._theme()))
        self._refresh_list()

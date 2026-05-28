"""Reports browser window — searchable archive + quick export.

Left rail: card-styled list of saved reports (date, kind chip,
file name) with an in-list full-text search box. Right pane:
rendered Markdown via ``QTextBrowser`` with theme-aware styling plus
a lightweight export toolbar for PDF / HTML.

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
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from ..reports.exporters import export_html, export_pdf, render_report_html
from ..reports.generator import daily_period
from ..reports.search import ReportHit, search_reports
from ..storage import session
from ..storage.models import Bucket, Report
from ..utils.logging import get_logger
from .icon import tinted_icon
from .progress import BusyOverlay
from .theme import LIGHT, Theme, resolve, with_accent

log = get_logger(__name__)


class _ReportSignals(QObject):
    done = Signal(object)  # (ReportResult)
    failed = Signal(str)  # error message


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
    """Render markdown to themed HTML for QTextBrowser and export."""

    return render_report_html(text, theme)


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


class _ReportHitCard(QWidget):
    """A report card with a search snippet shown beneath the header."""

    def __init__(self, report: Report, hit: ReportHit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report
        self.hit = hit

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

        snippet_label = QLabel(hit.snippet)
        snippet_label.setWordWrap(True)
        snippet_label.setProperty("role", "caption")
        file_label = QLabel(Path(report.markdown_path).name)
        file_label.setProperty("role", "caption")

        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(4)
        col.addLayout(top_row)
        col.addWidget(snippet_label)
        col.addWidget(file_label)


class ReportsWindow(QWidget):
    def __init__(self, config: RinConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("RIN — Reports")
        self.resize(1080, 680)

        self._current_markdown: str | None = None
        self._current_export_stem = "report"

        self._pool = QThreadPool.globalInstance()
        self._signals = _ReportSignals()
        self._signals.done.connect(self._on_report_done)
        self._signals.failed.connect(self._on_report_failed)

        self._report_search = QLineEdit()
        self._report_search.setPlaceholderText("Search report text…")
        self._report_search.setProperty("role", "search")
        self._report_search.returnPressed.connect(self._run_search)
        self._report_search.textChanged.connect(self._on_search_text_changed)
        self._report_search_btn = QPushButton("Search")
        self._report_search_btn.setProperty("primary", True)
        self._report_search_btn.setProperty("role", "search-attached")
        self._report_search_btn.clicked.connect(self._run_search)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(0)
        search_row.addWidget(self._report_search, 1)
        search_row.addWidget(self._report_search_btn)

        self._list = QListWidget()
        self._list.setProperty("role", "cards")
        self._list.setIconSize(QSize(0, 0))
        self._list.setSpacing(0)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setFrameShape(QFrame.Shape.NoFrame)

        self._viewer = QTextBrowser()
        self._viewer.setOpenExternalLinks(True)
        self._viewer.setFrameShape(QFrame.Shape.NoFrame)

        self._empty_state = _EmptyState(
            "Select a report",
            "Pick a report on the left, or generate today's report to get started.",
            icon_name="document",
        )
        self._viewer_stack = QStackedWidget()
        self._viewer_stack.addWidget(self._empty_state)
        self._viewer_stack.addWidget(self._viewer)

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

        self._export_pdf_btn = QPushButton("Export PDF…")
        self._export_pdf_btn.clicked.connect(self._export_current_pdf)
        self._export_html_btn = QPushButton("Export HTML…")
        self._export_html_btn.clicked.connect(self._export_current_html)
        self._set_export_enabled(False)

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

        export_row = QHBoxLayout()
        export_row.setContentsMargins(0, 0, 0, 8)
        export_row.setSpacing(8)
        export_label = QLabel("Export")
        export_label.setProperty("heading", "subtle")
        export_row.addWidget(export_label, 0, Qt.AlignmentFlag.AlignVCenter)
        export_row.addStretch()
        export_row.addWidget(self._export_pdf_btn)
        export_row.addWidget(self._export_html_btn)

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
        list_heading = QLabel("Saved reports")
        list_heading.setProperty("heading", "subtle")
        count_chip = QLabel("0")
        count_chip.setProperty("role", "chip")
        count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_chip.setMinimumWidth(28)
        meta_row.addWidget(list_heading)
        meta_row.addStretch()
        meta_row.addWidget(count_chip)
        side.addLayout(meta_row)
        self._list_heading = list_heading
        self._list_caption = count_chip

        side.addLayout(search_row)
        side.addWidget(self._list, 1)
        side.addLayout(action_row)

        side.addSpacing(8)
        arch_heading = QLabel("Archives")
        arch_heading.setProperty("heading", "subtle")
        side.addWidget(arch_heading)
        self._archives_list = QListWidget()
        self._archives_list.setProperty("role", "cards")
        self._archives_list.setSpacing(0)
        self._archives_list.setFrameShape(QFrame.Shape.NoFrame)
        self._archives_list.setMaximumHeight(180)
        self._archives_list.itemClicked.connect(self._on_archive_clicked)
        side.addWidget(self._archives_list)

        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(320)

        divider = QFrame()
        divider.setProperty("role", "divider-vert")
        divider.setFixedWidth(1)

        viewer_col = QVBoxLayout()
        viewer_col.setContentsMargins(24, 24, 24, 24)
        viewer_col.setSpacing(0)
        viewer_col.addLayout(export_row)
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

    def _all_reports(self) -> list[Report]:
        with session() as s:
            return s.scalars(select(Report).order_by(Report.period_start.desc())).all()

    def _reports_by_id(self, report_ids: list[int]) -> dict[int, Report]:
        if not report_ids:
            return {}
        with session() as s:
            rows = s.scalars(select(Report).where(Report.id.in_(report_ids))).all()
        return {report.id: report for report in rows}

    def _theme(self) -> Theme:
        try:
            return with_accent(resolve(self.config.ui.theme), self.config.ui.accent)
        except Exception:
            return LIGHT

    def _on_search_text_changed(self, text: str) -> None:
        if not text.strip():
            self._populate_report_list(self._all_reports())
            self._refresh_archives()

    def _run_search(self) -> None:
        query = self._report_search.text().strip()
        if not query:
            self._populate_report_list(self._all_reports())
            self._refresh_archives()
            return
        hits = search_reports(query)
        self._populate_hit_list(hits, query)
        self._refresh_archives()

    def _refresh_list(self) -> None:
        query = self._report_search.text().strip()
        if query:
            self._run_search()
            return
        self._populate_report_list(self._all_reports())
        self._refresh_archives()

    def _populate_report_list(self, rows: list[Report]) -> None:
        self._list.clear()
        self._list_heading.setText("Saved reports")
        self._list_caption.setText(str(len(rows)))
        if not rows:
            empty_item = QListWidgetItem("No reports yet — click Generate today.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty_item)
            return
        for report in rows:
            card = _ReportCard(report)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, report.markdown_path)
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

    def _populate_hit_list(self, hits: list[ReportHit], query: str) -> None:
        self._list.clear()
        self._list_heading.setText("Search hits")
        self._list_caption.setText(str(len(hits)))
        if not hits:
            empty_item = QListWidgetItem(f"No report text matched “{query}”.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty_item)
            return
        reports = self._reports_by_id([hit.report_id for hit in hits])
        added = 0
        for hit in hits:
            report = reports.get(hit.report_id)
            if report is None:
                continue
            card = _ReportHitCard(report, hit)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, report.markdown_path)
            self._list.addItem(item)
            self._list.setItemWidget(item, card)
            added += 1
        if added == 0:
            empty_item = QListWidgetItem("No saved report files are available for these hits.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty_item)

    def _refresh_archives(self) -> None:
        """Populate the Archives list with closed skill buckets."""

        self._archives_list.clear()
        try:
            with session() as s:
                rows = list(
                    s.scalars(
                        select(Bucket)
                        .where(Bucket.status == "archived")
                        .order_by(Bucket.closed_at.desc())
                    )
                )
        except Exception as exc:
            log.warning(f"Cannot load archives: {exc}")
            return
        if not rows:
            placeholder = QListWidgetItem("No archives yet")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._archives_list.addItem(placeholder)
            return
        for bucket in rows:
            label = f"{bucket.skill_name} · {bucket.key}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, bucket.archive_path)
            self._archives_list.addItem(item)

    def _show_markdown_path(self, path: str, *, label: str) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self._show_error(f"Could not open {label} {path}: {exc}")
            return
        self._show_markdown(text, export_stem=Path(path).stem)

    def _show_markdown(self, text: str, *, export_stem: str) -> None:
        self._current_markdown = text
        self._current_export_stem = export_stem or "report"
        self._set_export_enabled(True)
        self._viewer.setHtml(_md_to_html(text, self._theme()))
        self._viewer_stack.setCurrentWidget(self._viewer)

    def _show_error(self, message: str) -> None:
        self._current_markdown = None
        self._current_export_stem = "report"
        self._set_export_enabled(False)
        self._viewer.setPlainText(message)
        self._viewer_stack.setCurrentWidget(self._viewer)

    def _on_archive_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._show_markdown_path(str(path), label="archive")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._show_markdown_path(str(path), label="report")

    # --- export --------------------------------------------------------------------

    def _set_export_enabled(self, enabled: bool) -> None:
        self._export_pdf_btn.setEnabled(enabled)
        self._export_html_btn.setEnabled(enabled)

    def _prompt_export_path(self, caption: str, suffix: str, file_filter: str) -> Path | None:
        if not self._current_markdown:
            return None
        suggested = Path.home() / f"{self._current_export_stem}{suffix}"
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            caption,
            str(suggested),
            file_filter,
        )
        if not chosen:
            return None
        path = Path(chosen)
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        return path

    def _export_current_pdf(self) -> None:
        path = self._prompt_export_path("Export report as PDF", ".pdf", "PDF Files (*.pdf)")
        if path is None or self._current_markdown is None:
            return
        try:
            export_pdf(self._current_markdown, path, self._theme())
            log.info(f"Exported report PDF → {path}")
        except Exception as exc:
            log.warning(f"Could not export report PDF to {path}: {exc}")

    def _export_current_html(self) -> None:
        path = self._prompt_export_path("Export report as HTML", ".html", "HTML Files (*.html)")
        if path is None or self._current_markdown is None:
            return
        try:
            export_html(self._current_markdown, path, self._theme())
            log.info(f"Exported report HTML → {path}")
        except Exception as exc:
            log.warning(f"Could not export report HTML to {path}: {exc}")

    # --- generation (async) -------------------------------------------------------

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self._gen_today_btn, self._gen_week_btn, self._refresh_btn):
            btn.setEnabled(enabled)

    def _start_generation(self, kind: str, label: str) -> None:
        """Kick off a report-generation worker and raise the busy overlay."""

        if not self._busy.isHidden():
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
            export_stem = result.path.stem
        except AttributeError:
            body = str(result)
            export_stem = "report"
        self._show_markdown(body, export_stem=export_stem)
        self._refresh_list()

    def _on_report_failed(self, msg: str) -> None:
        self._busy.hide()
        self._set_actions_enabled(True)
        self._show_error(
            f"Report generation failed:\n\n{msg}\n\n"
            "Check rin.log for details, or run Tray → Generate diagnostic report."
        )

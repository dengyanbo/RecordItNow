"""Capture picker dialog used to seed a new Point of Interest."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ..storage import session
from ..storage.models import Analysis, Capture
from .poi_tab_widgets import _configure_table


class _CapturePickerDialog(QDialog):
    """Phase 2-B: pick a recent capture to seed a new PoI from."""

    _MAX_ROWS = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create PoI from capture")
        self.resize(720, 420)
        self._selected_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = QLabel(
            "Pick a recent capture. RIN will mine its text for the strongest "
            "regex / phrase / domain signal and pre-fill a new PoI editor."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "field-hint")
        layout.addWidget(hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Capture", "When", "Kind", "Summary"])
        _configure_table(self._table)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table, 1)

        self._empty_label = QLabel("No recent captures available.")
        self._empty_label.setProperty("role", "field-hint")
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Use this capture")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_captures()

    def selected_capture_id(self) -> int | None:
        return self._selected_id

    def accept(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        capture_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(capture_id, int):
            return
        self._selected_id = capture_id
        super().accept()

    def _on_double_click(self, _item: QTableWidgetItem) -> None:
        self.accept()

    def _load_captures(self) -> None:
        rows: list[tuple[int, str, datetime, str, str]] = []
        with session() as s:
            captures = list(
                s.scalars(
                    select(Capture)
                    .order_by(Capture.started_at.desc())
                    .limit(self._MAX_ROWS)
                )
            )
            for capture in captures:
                analysis = s.scalar(
                    select(Analysis)
                    .where(Analysis.capture_id == capture.id)
                    .order_by(Analysis.created_at.desc())
                )
                summary = (analysis.summary or "") if analysis else ""
                preview = summary.strip().splitlines()[0] if summary.strip() else ""
                if len(preview) > 140:
                    preview = preview[:137] + "…"
                rows.append(
                    (
                        capture.id,
                        f"cap-{capture.id}",
                        capture.started_at,
                        capture.kind,
                        preview,
                    )
                )

        if not rows:
            self._table.setRowCount(0)
            self._empty_label.show()
            self._ok_button.setEnabled(False)
            return

        self._empty_label.hide()
        self._ok_button.setEnabled(True)
        self._table.setRowCount(len(rows))
        for r, (capture_id, label, started_at, kind, preview) in enumerate(rows):
            id_item = QTableWidgetItem(label)
            id_item.setData(Qt.ItemDataRole.UserRole, capture_id)
            when = started_at.strftime("%Y-%m-%d %H:%M") if started_at else ""
            self._table.setItem(r, 0, id_item)
            self._table.setItem(r, 1, QTableWidgetItem(when))
            self._table.setItem(r, 2, QTableWidgetItem(kind))
            self._table.setItem(r, 3, QTableWidgetItem(preview))
        self._table.selectRow(0)



__all__ = ["_CapturePickerDialog"]

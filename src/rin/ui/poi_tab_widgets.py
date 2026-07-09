"""Shared widgets and styling helpers for the Topics & PoIs settings UI."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


def _form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)
    form.setContentsMargins(0, 0, 0, 0)
    return form


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "field-label")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "field-hint")
    label.setWordWrap(True)
    return label


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(10)

    heading = QLabel(title)
    heading.setProperty("heading", "h2")
    layout.addWidget(heading)
    return card, layout


def _configure_table(table: QTableWidget) -> None:
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setMinimumHeight(180)


def _item(text: str, *, align: Qt.AlignmentFlag | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if align is not None:
        item.setTextAlignment(align)
    return item



__all__ = [
    "_card",
    "_configure_table",
    "_form_layout",
    "_hint",
    "_item",
    "_label",
]

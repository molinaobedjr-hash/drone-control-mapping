"""Timestamped event timeline shown in the main window."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class TimelinePanel(QWidget):
    """Display synchronized acquisition and operator events."""

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                "Monotonic Time (s)",
                "UTC",
                "Source",
                "Event / Data",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Interactive,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 105)

        group = QGroupBox(
            "Synchronized Timeline"
        )
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(self.table)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

    def add_row(
        self,
        monotonic_s: float,
        utc_text: str,
        source: str,
        description: str,
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        for column, value in enumerate(
            (
                f"{monotonic_s:.9f}",
                utc_text,
                source,
                description,
            )
        ):
            self.table.setItem(
                row,
                column,
                QTableWidgetItem(value),
            )

        self.table.scrollToBottom()

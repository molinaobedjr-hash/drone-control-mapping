from __future__ import annotations
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem

class TimelinePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Monotonic Time (s)", "UTC", "Source", "Event / Data"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        group = QGroupBox("Synchronized Timeline")
        gl = QVBoxLayout(group)
        gl.addWidget(self.table)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

    def add_row(self, monotonic_s: float, utc_text: str, source: str, description: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate([
            f"{monotonic_s:.9f}", utc_text, source, description
        ]):
            self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.scrollToBottom()

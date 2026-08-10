from __future__ import annotations
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel, QProgressBar

class DatasetPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller_count = QLabel("0")
        self.mavlink_count = QLabel("0")
        self.sdr_count = QLabel("0")
        self.event_count = QLabel("0")

        form = QFormLayout()
        form.addRow("Controller samples", self.controller_count)
        form.addRow("MAVLink messages", self.mavlink_count)
        form.addRow("SDR records", self.sdr_count)
        form.addRow("Experiment markers", self.event_count)

        self.quality_bar = QProgressBar()
        self.quality_bar.setRange(0, 100)
        self.quality_bar.setValue(0)
        self.quality_bar.setFormat("Dataset readiness: %p%")

        group = QGroupBox("Dataset Quality")
        gl = QVBoxLayout(group)
        gl.addLayout(form)
        gl.addWidget(self.quality_bar)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

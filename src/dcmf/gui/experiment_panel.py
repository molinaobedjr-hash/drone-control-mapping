from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLineEdit, QTextEdit, QPushButton, QComboBox

class ExperimentPanel(QWidget):
    start_requested = Signal(dict)
    stop_requested = Signal()
    marker_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name_edit = QLineEdit()
        self.operator_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(70)

        form = QFormLayout()
        form.addRow("Experiment", self.name_edit)
        form.addRow("Operator", self.operator_edit)
        form.addRow("Notes", self.notes_edit)

        self.start_button = QPushButton("Start Experiment")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)

        self.marker_combo = QComboBox()
        self.marker_combo.addItems([
            "ROLL_RIGHT", "ROLL_LEFT",
            "PITCH_FORWARD", "PITCH_BACK",
            "YAW_RIGHT", "YAW_LEFT",
            "THROTTLE_UP", "THROTTLE_DOWN",
            "ARM", "DISARM", "RTL", "LOITER", "CUSTOM"
        ])
        self.marker_button = QPushButton("Mark Event")
        self.marker_button.setEnabled(False)

        marker_row = QHBoxLayout()
        marker_row.addWidget(self.marker_combo)
        marker_row.addWidget(self.marker_button)

        group = QGroupBox("Experiment")
        gl = QVBoxLayout(group)
        gl.addLayout(form)
        gl.addLayout(buttons)
        gl.addLayout(marker_row)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

        self.start_button.clicked.connect(self._emit_start)
        self.stop_button.clicked.connect(self._emit_stop)
        self.marker_button.clicked.connect(
            lambda: self.marker_requested.emit(self.marker_combo.currentText())
        )

    def _emit_start(self) -> None:
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.marker_button.setEnabled(True)
        self.start_requested.emit({
            "name": self.name_edit.text().strip() or "Untitled Experiment",
            "operator": self.operator_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        })

    def _emit_stop(self) -> None:
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.marker_button.setEnabled(False)
        self.stop_requested.emit()

"""Live acquisition counters shown in the main window."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class DatasetPanel(QWidget):
    """Show live counts without claiming completed-session quality."""

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.controller_count = QLabel("0")
        self.mavlink_count = QLabel("0")
        self.sdr_count = QLabel("0")
        self.event_count = QLabel("0")

        form = QFormLayout()
        form.addRow(
            "Controller samples",
            self.controller_count,
        )
        form.addRow(
            "MAVLink messages",
            self.mavlink_count,
        )
        form.addRow(
            "SDR records",
            self.sdr_count,
        )
        form.addRow(
            "Experiment/operator events",
            self.event_count,
        )

        review_hint = QLabel(
            "After stopping an experiment, use Experiment > "
            "Review Completed Sessions for data-quality checks."
        )
        review_hint.setWordWrap(True)

        group = QGroupBox(
            "Live Dataset Counts"
        )
        group_layout = QVBoxLayout(group)
        group_layout.addLayout(form)
        group_layout.addWidget(review_hint)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

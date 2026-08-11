"""Integrated completed-session quality review dialog."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dcmf.analysis.session_quality import (
    FAIL,
    PASS,
    WARNING,
    SessionQualityReport,
    evaluate_session,
    list_experiments,
)
from dcmf.config.settings import AppSettings


LIGHT_STATUS_COLORS = {
    PASS: QColor("#2e7d32"),
    WARNING: QColor("#b26a00"),
    FAIL: QColor("#c62828"),
}
DARK_STATUS_COLORS = {
    PASS: QColor("#66bb6a"),
    WARNING: QColor("#ffb74d"),
    FAIL: QColor("#ef5350"),
}
STATUS_LABELS = {
    PASS: "Passed",
    WARNING: "Warning",
    FAIL: "Failed",
}


def _local_datetime(
    utc_iso: object,
) -> datetime | None:
    """Parse a stored UTC timestamp and convert it to local time."""
    if not isinstance(utc_iso, str) or not utc_iso:
        return None

    try:
        parsed = datetime.fromisoformat(
            utc_iso.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    return parsed.astimezone()


def _friendly_datetime(
    utc_iso: object,
    *,
    include_seconds: bool = True,
) -> str:
    """Return a concise local date/time for display in the GUI."""
    local = _local_datetime(utc_iso)
    if local is None:
        return "Not recorded"

    hour = local.strftime("%I").lstrip("0") or "12"
    seconds = (
        f":{local:%S}"
        if include_seconds
        else ""
    )
    zone = local.tzname() or "local time"
    return (
        f"{local:%b} {local.day}, {local:%Y} at "
        f"{hour}:{local:%M}{seconds} {local:%p} {zone}"
    )


def _friendly_duration(
    started_monotonic_ns: object,
    ended_monotonic_ns: object,
) -> str:
    """Format a monotonic interval without exposing raw nanoseconds."""
    try:
        duration_seconds = max(
            0,
            round(
                (
                    int(ended_monotonic_ns)
                    - int(started_monotonic_ns)
                )
                / 1_000_000_000
            ),
        )
    except (TypeError, ValueError):
        return "Not recorded"

    hours, remainder = divmod(
        duration_seconds,
        3600,
    )
    minutes, seconds = divmod(
        remainder,
        60,
    )
    parts = []
    if hours:
        parts.append(
            f"{hours} hr"
        )
    if minutes:
        parts.append(
            f"{minutes} min"
        )
    if seconds or not parts:
        parts.append(
            f"{seconds} sec"
        )
    return " ".join(parts)


def _timestamp_tooltip(
    utc_iso: object,
    utc_ns: object,
) -> str:
    """Keep the exact stored timestamp available without crowding the UI."""
    lines = [
        f"Stored UTC: {utc_iso or 'Not recorded'}"
    ]
    if utc_ns is not None:
        try:
            lines.append(
                f"UTC nanoseconds: {int(utc_ns):,}"
            )
        except (TypeError, ValueError):
            lines.append(
                f"UTC nanoseconds: {utc_ns}"
            )
    return "\n".join(lines)


class SessionQualityWorker(QThread):
    """Evaluate a selected session without blocking the GUI thread."""

    review_completed = Signal(object)
    review_failed = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        experiment_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.experiment_id = experiment_id

    def run(self) -> None:
        try:
            report = evaluate_session(
                database_path=(
                    self.settings.database_path
                ),
                experiment_root=(
                    self.settings.experiment_directory
                ),
                export_root=(
                    self.settings.export_directory
                ),
                iq_root=self.settings.iq_directory,
                experiment_id=self.experiment_id,
            )
        except Exception as exc:
            self.review_failed.emit(str(exc))
            return

        self.review_completed.emit(report)


class SessionReviewDialog(QDialog):
    """Select and review completed DCMF experiment quality."""

    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker: SessionQualityWorker | None = None

        self.setWindowTitle(
            "Completed Session Review"
        )
        self.resize(1120, 780)

        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(520)
        self.refresh_button = QPushButton(
            "Refresh Sessions"
        )
        self.review_button = QPushButton(
            "Review Selected"
        )

        selector = QHBoxLayout()
        selector.addWidget(self.session_combo, 1)
        selector.addWidget(self.refresh_button)
        selector.addWidget(self.review_button)

        self.overall_label = QLabel(
            "Select a completed experiment."
        )
        overall_font = self.overall_label.font()
        overall_font.setBold(True)
        overall_font.setPointSize(
            overall_font.pointSize() + 2
        )
        self.overall_label.setFont(overall_font)
        self.overall_label.setWordWrap(True)

        self.name_label = QLabel("—")
        self.id_label = QLabel("—")
        self.started_label = QLabel("—")
        self.ended_label = QLabel("—")
        self.duration_label = QLabel("—")
        self.package_label = QLabel("—")
        self.export_label = QLabel("—")
        for label in (
            self.id_label,
            self.started_label,
            self.ended_label,
            self.package_label,
            self.export_label,
        ):
            label.setTextInteractionFlags(
                label.textInteractionFlags()
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            label.setWordWrap(True)

        summary_form = QFormLayout()
        summary_form.addRow(
            "Experiment",
            self.name_label,
        )
        summary_form.addRow(
            "Started",
            self.started_label,
        )
        summary_form.addRow(
            "Ended",
            self.ended_label,
        )
        summary_form.addRow(
            "Duration",
            self.duration_label,
        )
        summary_form.addRow(
            "Experiment ID",
            self.id_label,
        )
        summary_form.addRow(
            "Package",
            self.package_label,
        )
        summary_form.addRow(
            "Export",
            self.export_label,
        )

        summary_group = QGroupBox(
            "Session"
        )
        summary_layout = QVBoxLayout(
            summary_group
        )
        summary_layout.addWidget(
            self.overall_label
        )
        summary_layout.addLayout(
            summary_form
        )

        self.counts_table = QTableWidget(
            0,
            2,
        )
        self.counts_table.setHorizontalHeaderLabels(
            ["Source", "Count"]
        )
        self._configure_table(
            self.counts_table
        )
        self.counts_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.counts_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        counts_group = QGroupBox(
            "Recorded Data"
        )
        counts_layout = QVBoxLayout(
            counts_group
        )
        counts_layout.addWidget(
            self.counts_table
        )

        top = QHBoxLayout()
        top.addWidget(summary_group, 3)
        top.addWidget(counts_group, 2)

        self.checks_table = QTableWidget(
            0,
            3,
        )
        self.checks_table.setHorizontalHeaderLabels(
            ["Status", "Check", "Result"]
        )
        self._configure_table(
            self.checks_table
        )
        checks_header = (
            self.checks_table.horizontalHeader()
        )
        checks_header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Fixed,
        )
        checks_header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        checks_header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        self.checks_table.setColumnWidth(0, 95)

        checks_group = QGroupBox(
            "Quality Checks"
        )
        checks_layout = QVBoxLayout(
            checks_group
        )
        checks_layout.addWidget(
            self.checks_table
        )

        self.coverage_table = QTableWidget(
            0,
            4,
        )
        self.coverage_table.setHorizontalHeaderLabels(
            [
                "Action",
                "Done",
                "Goal",
                "Status",
            ]
        )
        self._configure_table(
            self.coverage_table
        )
        coverage_header = (
            self.coverage_table.horizontalHeader()
        )
        coverage_header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        for column in (1, 2, 3):
            coverage_header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        coverage_group = QGroupBox(
            "Guided Trial Coverage"
        )
        coverage_layout = QVBoxLayout(
            coverage_group
        )
        coverage_layout.addWidget(
            self.coverage_table
        )

        tables = QHBoxLayout()
        tables.addWidget(checks_group, 3)
        tables.addWidget(coverage_group, 2)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        button_box.rejected.connect(
            self.reject
        )

        layout = QVBoxLayout(self)
        layout.addLayout(selector)
        layout.addLayout(top, 2)
        layout.addLayout(tables, 5)
        layout.addWidget(button_box)

        self.refresh_button.clicked.connect(
            self.refresh_sessions
        )
        self.review_button.clicked.connect(
            self.review_selected
        )
        self.session_combo.currentIndexChanged.connect(
            self._selection_changed
        )

        self.refresh_sessions()

    @staticmethod
    def _configure_table(
        table: QTableWidget,
    ) -> None:
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)

    def _status_color(
        self,
        status: str,
    ) -> QColor:
        base = self.palette().color(
            QPalette.ColorRole.Base
        )
        colors = (
            DARK_STATUS_COLORS
            if base.lightness() < 128
            else LIGHT_STATUS_COLORS
        )
        return colors[status]

    def refresh_sessions(self) -> None:
        selected_id = self.session_combo.currentData()
        try:
            experiments = list_experiments(
                self.settings.database_path,
                completed_only=True,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Session Review",
                f"Could not list completed experiments:\n\n{exc}",
            )
            return

        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for experiment in experiments:
            started = _friendly_datetime(
                experiment.get("started_utc_iso"),
                include_seconds=False,
            )
            label = (
                f"{started}  —  "
                f"{experiment.get('name') or 'Untitled Experiment'}"
            )
            self.session_combo.addItem(
                label,
                experiment["id"],
            )
            item_index = self.session_combo.count() - 1
            self.session_combo.setItemData(
                item_index,
                (
                    f"Experiment ID: {experiment['id']}\n"
                    f"{_timestamp_tooltip(experiment.get('started_utc_iso'), experiment.get('started_utc_ns'))}"
                ),
                Qt.ItemDataRole.ToolTipRole,
            )

        if selected_id:
            selected_index = (
                self.session_combo.findData(
                    selected_id
                )
            )
            if selected_index >= 0:
                self.session_combo.setCurrentIndex(
                    selected_index
                )
        self.session_combo.blockSignals(False)

        has_sessions = self.session_combo.count() > 0
        self.review_button.setEnabled(
            has_sessions
        )
        if has_sessions:
            self.review_selected()
        else:
            self.overall_label.setText(
                "No completed experiments were found."
            )

    def _selection_changed(self) -> None:
        self.overall_label.setText(
            "Click Review Selected to run quality checks."
        )

    def review_selected(self) -> None:
        experiment_id = self.session_combo.currentData()
        if not experiment_id:
            return
        if (
            self._worker is not None
            and self._worker.isRunning()
        ):
            return

        self.review_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.session_combo.setEnabled(False)
        self.overall_label.setText(
            "Reviewing session…"
        )

        worker = SessionQualityWorker(
            settings=self.settings,
            experiment_id=str(experiment_id),
            parent=self,
        )
        worker.review_completed.connect(
            self._display_report
        )
        worker.review_failed.connect(
            self._review_failed
        )
        worker.finished.connect(
            self._worker_finished
        )
        self._worker = worker
        worker.start()

    def _display_report(
        self,
        report: SessionQualityReport,
    ) -> None:
        color = self._status_color(
            report.overall_status
        )
        counts = report.status_counts
        result_message = {
            PASS: "Ready — all checks passed.",
            WARNING: "Usable with notes — review the warnings below.",
            FAIL: "Needs attention — required checks failed.",
        }[report.overall_status]
        self.overall_label.setText(
            f"{STATUS_LABELS[report.overall_status]}: "
            f"{result_message}\n"
            f"{counts[PASS]} passed  •  "
            f"{counts[WARNING]} warning"
            f"{'s' if counts[WARNING] != 1 else ''}  •  "
            f"{counts[FAIL]} failed"
        )
        self.overall_label.setStyleSheet(
            f"color: {color.name()};"
        )

        experiment = report.experiment
        self.name_label.setText(
            str(experiment.get("name") or "—")
        )
        self.id_label.setText(
            str(experiment.get("id") or "—")
        )
        self.started_label.setText(
            _friendly_datetime(
                experiment.get("started_utc_iso")
            )
        )
        self.started_label.setToolTip(
            _timestamp_tooltip(
                experiment.get("started_utc_iso"),
                experiment.get("started_utc_ns"),
            )
        )
        self.ended_label.setText(
            _friendly_datetime(
                experiment.get("ended_utc_iso")
            )
        )
        self.ended_label.setToolTip(
            _timestamp_tooltip(
                experiment.get("ended_utc_iso"),
                experiment.get("ended_utc_ns"),
            )
        )
        self.duration_label.setText(
            _friendly_duration(
                experiment.get("started_monotonic_ns"),
                experiment.get("ended_monotonic_ns"),
            )
        )
        self.package_label.setText(
            report.package_directory or "Not found"
        )
        self.export_label.setText(
            report.export_directory or "Not found"
        )

        count_labels = (
            ("Controller samples", "controller_samples"),
            ("MAVLink messages", "mavlink_messages"),
            ("MAVLink heartbeats", "heartbeats"),
            ("SDR records", "sdr_records"),
            ("All events", "events"),
            ("Manual markers", "manual_markers"),
        )
        self.counts_table.setRowCount(
            len(count_labels)
        )
        for row, (label, key) in enumerate(
            count_labels
        ):
            self.counts_table.setItem(
                row,
                0,
                QTableWidgetItem(label),
            )
            self.counts_table.setItem(
                row,
                1,
                QTableWidgetItem(
                    f"{report.counts.get(key, 0):,}"
                ),
            )

        self.checks_table.setRowCount(
            len(report.checks)
        )
        for row, check in enumerate(
            report.checks
        ):
            status_item = QTableWidgetItem(
                STATUS_LABELS[check.status]
            )
            status_item.setForeground(
                self._status_color(
                    check.status
                )
            )
            status_font = QFont(
                status_item.font()
            )
            status_font.setBold(True)
            status_item.setFont(status_font)
            self.checks_table.setItem(
                row,
                0,
                status_item,
            )
            status_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            self.checks_table.setItem(
                row,
                1,
                QTableWidgetItem(check.title),
            )
            self.checks_table.setItem(
                row,
                2,
                QTableWidgetItem(check.message),
            )
        self.checks_table.resizeRowsToContents()

        coverage = report.guided_trials.get(
            "coverage",
            {},
        )
        self.coverage_table.setRowCount(
            len(coverage)
        )
        for row, (action, item) in enumerate(
            coverage.items()
        ):
            completed = int(
                item["completed"]
            )
            target = int(item["target"])
            status = (
                "Complete"
                if completed >= target
                else f"{target - completed} needed"
            )
            self.coverage_table.setItem(
                row,
                0,
                QTableWidgetItem(action),
            )
            self.coverage_table.setItem(
                row,
                1,
                QTableWidgetItem(str(completed)),
            )
            self.coverage_table.setItem(
                row,
                2,
                QTableWidgetItem(str(target)),
            )
            status_item = QTableWidgetItem(
                status
            )
            status_item.setForeground(
                self._status_color(
                    PASS
                    if completed >= target
                    else WARNING
                )
            )
            self.coverage_table.setItem(
                row,
                3,
                status_item,
            )
            for column in (1, 2, 3):
                table_item = self.coverage_table.item(
                    row,
                    column,
                )
                table_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )

    def _review_failed(
        self,
        message: str,
    ) -> None:
        self.overall_label.setText(
            "Session review failed."
        )
        self.overall_label.setStyleSheet(
            f"color: {self._status_color(FAIL).name()};"
        )
        QMessageBox.warning(
            self,
            "Session Review",
            f"Could not review the selected experiment:\n\n{message}",
        )

    def _worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.review_button.setEnabled(
            self.session_combo.count() > 0
        )
        self.refresh_button.setEnabled(True)
        self.session_combo.setEnabled(True)

    def closeEvent(self, event) -> None:
        worker = self._worker
        if (
            worker is not None
            and worker.isRunning()
            and not worker.wait(10_000)
        ):
            event.ignore()
            return
        event.accept()

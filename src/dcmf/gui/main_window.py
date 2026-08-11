"""Main integrated DCMF window."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dcmf.acquisition.controller.mapping import (
    load_mapping,
    save_mapping,
)
from dcmf.acquisition.controller.reader import (
    ControllerReader,
    ControllerSample,
)
from dcmf.acquisition.mavlink.reader import (
    MavlinkPacket,
    MavlinkReader,
    discover_serial_ports,
)
from dcmf.acquisition.sdr.reader import (
    SdrCaptureConfig,
    SdrCaptureWorker,
    discover_uhd_devices,
    uhd_backend_status,
)
from dcmf.config.settings import AppSettings
from dcmf.core.event_bus import DcmfEvent, EventBus
from dcmf.core.guided_trials import GUIDED_ACTIONS
from dcmf.database.writer import DatabaseWriter
from dcmf.experiments.exporter import (
    ExperimentExportWorker,
    export_experiment,
)
from dcmf.experiments.packaging import (
    ExperimentPackage,
    create_experiment_package,
)
from dcmf.gui.controller_calibration_dialog import (
    ControllerCalibrationDialog,
)
from dcmf.gui.controller_panel import ControllerPanel
from dcmf.gui.dataset_panel import DatasetPanel
from dcmf.gui.experiment_panel import ExperimentPanel
from dcmf.gui.guided_trial_panel import GuidedTrialPanel
from dcmf.gui.mavlink_panel import MavlinkPanel
from dcmf.gui.sdr_panel import SdrPanel
from dcmf.gui.session_review_dialog import (
    SessionReviewDialog,
)
from dcmf.gui.timeline_panel import TimelinePanel
from dcmf.utils.timestamps import MasterClock


class MainWindow(QMainWindow):
    """Single-window interface for synchronized drone data acquisition."""

    def __init__(
        self,
        settings: AppSettings,
    ) -> None:
        super().__init__()

        self.settings = settings
        self.logger = logging.getLogger(
            "dcmf.experiments"
        )
        self.event_bus = EventBus(self)

        self.database_writer = DatabaseWriter(
            settings.database_path,
            self,
        )
        self.database_writer.experiment_closed.connect(
            self._on_database_experiment_closed
        )
        self.database_writer.command_failed.connect(
            self._on_database_command_failed
        )
        self.database_writer.start()

        self.controller_mapping = load_mapping(
            settings.controller_mapping_path
        )
        self.calibration_dialog: (
            ControllerCalibrationDialog | None
        ) = None

        self._controller_sample_number = 0
        self._mavlink_message_number = 0
        self._sdr_record_number = 0
        self._experiment_packages: dict[
            str,
            ExperimentPackage,
        ] = {}
        self._export_workers: dict[
            str,
            ExperimentExportWorker,
        ] = {}

        self.mavlink_reader: (
            MavlinkReader | None
        ) = None
        self.sdr_worker: (
            SdrCaptureWorker | None
        ) = None
        self._experiment_stop_pending = False

        self.setWindowTitle(
            f"{settings.application_name} — v{settings.version}"
        )
        self.resize(
            settings.window_width,
            settings.window_height,
        )
        self.setMinimumSize(
            1100,
            700,
        )

        self.experiment_panel = ExperimentPanel()
        self.guided_trial_panel = GuidedTrialPanel()
        self.controller_panel = ControllerPanel()
        self.controller_panel.set_mapping(
            self.controller_mapping
        )

        self.mavlink_panel = MavlinkPanel(
            default_baud=settings.mavlink_baud
        )
        self.sdr_panel = SdrPanel(
            center_hz=settings.sdr_center_frequency_hz,
            sample_rate_hz=settings.sdr_sample_rate_hz,
            gain_db=settings.sdr_gain_db,
        )
        self.timeline_panel = TimelinePanel()
        self.dataset_panel = DatasetPanel()

        self._build_menu()
        self._build_toolbar()
        self._build_layout()
        self._connect_signals()

        self.statusBar().showMessage(
            f"Ready | Database: {settings.database_path}"
        )

        self.event_bus.event_published.connect(
            self._on_event
        )
        self.event_bus.event_published.connect(
            self.database_writer.record_event
        )

        self.controller_reader = ControllerReader(
            self
        )
        self.controller_reader.connection_changed.connect(
            self._on_controller_connection
        )
        self.controller_reader.sample_received.connect(
            self._on_controller_sample
        )
        self.controller_reader.error_occurred.connect(
            self._on_controller_error
        )
        self.controller_reader.start()

        self._refresh_serial_ports()
        self._refresh_sdr_devices()

        self.event_bus.publish(
            "SYSTEM",
            "APPLICATION_READY",
            {
                "version":
                    settings.version,
                "database":
                    str(settings.database_path),
                "controller_mapping_complete":
                    self.controller_mapping.complete,
            },
        )

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu(
            "&File"
        )

        exit_action = QAction(
            "E&xit",
            self,
        )
        exit_action.triggered.connect(
            self.close
        )
        file_menu.addAction(
            exit_action
        )

        experiment_menu = (
            self.menuBar().addMenu(
                "&Experiment"
            )
        )

        self.menu_start_action = QAction(
            "&Start",
            self,
        )
        self.menu_stop_action = QAction(
            "S&top",
            self,
        )

        experiment_menu.addAction(
            self.menu_start_action
        )
        experiment_menu.addAction(
            self.menu_stop_action
        )
        experiment_menu.addSeparator()

        self.review_sessions_action = QAction(
            "Review Completed Sessions...",
            self,
        )
        self.review_sessions_action.triggered.connect(
            self._open_session_review
        )
        experiment_menu.addAction(
            self.review_sessions_action
        )

        tools_menu = self.menuBar().addMenu(
            "&Tools"
        )

        self.calibrate_action = QAction(
            "Calibrate TX16S...",
            self,
        )
        self.calibrate_action.triggered.connect(
            self._open_controller_calibration
        )
        tools_menu.addAction(
            self.calibrate_action
        )

        help_menu = self.menuBar().addMenu(
            "&Help"
        )

        about_action = QAction(
            "&About",
            self,
        )
        about_action.triggered.connect(
            self._show_about
        )
        help_menu.addAction(
            about_action
        )

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(
            "Main",
            self,
        )
        toolbar.setMovable(False)

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            toolbar,
        )

        self.toolbar_start_action = QAction(
            "Start",
            self,
        )
        self.toolbar_stop_action = QAction(
            "Stop",
            self,
        )
        self.toolbar_mark_action = QAction(
            "Mark Event",
            self,
        )
        self.toolbar_calibrate_action = QAction(
            "Calibrate TX16S",
            self,
        )

        self.toolbar_stop_action.setEnabled(
            False
        )
        self.toolbar_mark_action.setEnabled(
            False
        )

        toolbar.addAction(
            self.toolbar_start_action
        )
        toolbar.addAction(
            self.toolbar_stop_action
        )
        toolbar.addAction(
            self.toolbar_mark_action
        )
        toolbar.addSeparator()
        toolbar.addAction(
            self.toolbar_calibrate_action
        )

        self.toolbar_calibrate_action.triggered.connect(
            self._open_controller_calibration
        )

    def _build_layout(self) -> None:
        left_content = QWidget()
        left_layout = QVBoxLayout(
            left_content
        )
        left_layout.addWidget(
            self.experiment_panel
        )
        left_layout.addWidget(
            self.guided_trial_panel
        )
        left_layout.addWidget(
            self.controller_panel
        )
        left_layout.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(
            QFrame.Shape.NoFrame
        )
        left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        left_scroll.setMinimumWidth(360)
        left_scroll.setWidget(left_content)

        top_right = QWidget()
        top_right_layout = QHBoxLayout(
            top_right
        )
        top_right_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        top_right_layout.addWidget(
            self.mavlink_panel,
            1,
        )
        top_right_layout.addWidget(
            self.sdr_panel,
            1,
        )

        right_splitter = QSplitter(
            Qt.Orientation.Vertical
        )
        right_splitter.addWidget(
            top_right
        )
        right_splitter.addWidget(
            self.timeline_panel
        )
        right_splitter.addWidget(
            self.dataset_panel
        )

        right_splitter.setStretchFactor(
            0,
            3,
        )
        right_splitter.setStretchFactor(
            1,
            4,
        )
        right_splitter.setStretchFactor(
            2,
            1,
        )

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )
        splitter.addWidget(left_scroll)
        splitter.addWidget(
            right_splitter
        )
        splitter.setStretchFactor(
            0,
            1,
        )
        splitter.setStretchFactor(
            1,
            4,
        )
        splitter.setSizes(
            [360, 1140]
        )

        central = QWidget()
        layout = QVBoxLayout(
            central
        )
        layout.addWidget(
            splitter
        )
        self.setCentralWidget(
            central
        )

    def _connect_signals(self) -> None:
        self.experiment_panel.start_requested.connect(
            self._start_experiment
        )
        self.experiment_panel.stop_requested.connect(
            self._stop_experiment
        )
        self.experiment_panel.marker_requested.connect(
            self._mark_event
        )
        self.guided_trial_panel.trial_started.connect(
            self._start_guided_trial
        )
        self.guided_trial_panel.trial_ended.connect(
            self._end_guided_trial
        )

        self.mavlink_panel.refresh_requested.connect(
            self._refresh_serial_ports
        )
        self.mavlink_panel.connect_requested.connect(
            self._connect_mavlink
        )
        self.mavlink_panel.disconnect_requested.connect(
            self._disconnect_mavlink
        )

        self.sdr_panel.refresh_requested.connect(
            self._refresh_sdr_devices
        )
        self.sdr_panel.start_capture_requested.connect(
            self._start_sdr_capture
        )
        self.sdr_panel.stop_capture_requested.connect(
            self._stop_sdr_capture
        )

        self.toolbar_start_action.triggered.connect(
            lambda:
                self.experiment_panel.start_button.click()
        )
        self.toolbar_stop_action.triggered.connect(
            lambda:
                self.experiment_panel.stop_button.click()
        )
        self.toolbar_mark_action.triggered.connect(
            lambda:
                self.experiment_panel.marker_button.click()
        )

        self.menu_start_action.triggered.connect(
            lambda:
                self.experiment_panel.start_button.click()
        )
        self.menu_stop_action.triggered.connect(
            lambda:
                self.experiment_panel.stop_button.click()
        )

    # -------- Controller calibration --------

    def _open_controller_calibration(
        self,
    ) -> None:
        if (
            self.calibration_dialog is not None
            and self.calibration_dialog.isVisible()
        ):
            self.calibration_dialog.raise_()
            self.calibration_dialog.activateWindow()
            return

        dialog = ControllerCalibrationDialog(
            mapping=self.controller_mapping,
            parent=self,
        )
        self.calibration_dialog = dialog

        result = dialog.exec()

        if result:
            self.controller_mapping = dialog.mapping

            save_mapping(
                self.settings.controller_mapping_path,
                self.controller_mapping,
            )

            self.controller_panel.set_mapping(
                self.controller_mapping
            )

            self.event_bus.publish(
                "CONTROLLER",
                "MAPPING_SAVED",
                {
                    "path":
                        str(
                            self.settings.controller_mapping_path
                        ),
                    "complete":
                        self.controller_mapping.complete,
                },
            )

        self.calibration_dialog = None

    # -------- Controller acquisition --------

    def _on_controller_connection(
        self,
        connected: bool,
        description: str,
    ) -> None:
        self.controller_panel.set_connection(
            connected,
            description,
        )

        self.event_bus.publish(
            "CONTROLLER",
            (
                "CONNECTED"
                if connected
                else "DISCONNECTED"
            ),
            {
                "description":
                    description,
            },
        )

    def _on_controller_sample(
        self,
        sample: ControllerSample,
    ) -> None:
        self.controller_panel.set_sample(
            sample.axes,
            sample.buttons,
            sample.hats,
        )

        if self.calibration_dialog is not None:
            self.calibration_dialog.update_controller_sample(
                sample.axes
            )

        mapped = {
            control:
                self.controller_mapping.map_value(
                    control,
                    sample.axes,
                )
            for control in (
                "roll",
                "pitch",
                "yaw",
                "throttle",
            )
        }

        self.event_bus.publish(
            "CONTROLLER",
            "SAMPLE",
            {
                "device":
                    sample.device_name,
                "axes":
                    sample.axes,
                "buttons":
                    sample.buttons,
                "hats":
                    sample.hats,
                "mapped":
                    mapped,
            },
        )

    def _on_controller_error(
        self,
        message: str,
    ) -> None:
        self.controller_panel.set_connection(
            False,
            message,
        )

        self.event_bus.publish(
            "CONTROLLER",
            "ERROR",
            {
                "message":
                    message,
            },
        )

    # -------- MAVLink --------

    def _refresh_serial_ports(
        self,
    ) -> None:
        try:
            ports = discover_serial_ports()
            self.mavlink_panel.set_ports(
                ports
            )

            self.event_bus.publish(
                "MAVLINK",
                "PORT_SCAN",
                {
                    "count":
                        len(ports),
                    "ports":
                        [
                            port.device
                            for port in ports
                        ],
                },
            )
        except Exception as exc:
            self.mavlink_panel.show_error(
                str(exc)
            )

    def _connect_mavlink(
        self,
        port: str,
        baud: int,
    ) -> None:
        if (
            self.mavlink_reader is not None
            and self.mavlink_reader.isRunning()
        ):
            return

        reader = MavlinkReader(
            port=port,
            baud=baud,
            parent=self,
        )

        reader.connection_changed.connect(
            self._on_mavlink_connection
        )
        reader.packet_received.connect(
            self._on_mavlink_packet
        )
        reader.error_occurred.connect(
            self._on_mavlink_error
        )
        reader.finished.connect(
            self._on_mavlink_reader_finished
        )

        self.mavlink_reader = reader

        self.mavlink_panel.set_connection(
            True,
            f"Opening {port}...",
        )

        reader.start()

    def _disconnect_mavlink(
        self,
    ) -> None:
        reader = self.mavlink_reader
        if reader is None:
            return

        reader.stop()
        self.mavlink_reader = None

        self.mavlink_panel.set_connection(
            False,
            "Disconnected",
        )

    def _on_mavlink_connection(
        self,
        connected: bool,
        description: str,
    ) -> None:
        self.mavlink_panel.set_connection(
            connected,
            description,
        )

        self.event_bus.publish(
            "MAVLINK",
            (
                "CONNECTED"
                if connected
                else "DISCONNECTED"
            ),
            {
                "description":
                    description,
            },
        )

    def _on_mavlink_packet(
        self,
        packet: MavlinkPacket,
    ) -> None:
        self._mavlink_message_number += 1

        self.mavlink_panel.set_message_count(
            self._mavlink_message_number
        )
        self.mavlink_panel.add_packet(
            packet.message_name,
            packet.system_id,
            packet.component_id,
            packet.decoded,
        )

        self.event_bus.publish(
            "MAVLINK",
            "MESSAGE",
            {
                "direction":
                    "RX",
                "message_name":
                    packet.message_name,
                "message_id":
                    packet.message_id,
                "system_id":
                    packet.system_id,
                "component_id":
                    packet.component_id,
                "raw_hex":
                    packet.raw_hex,
                "decoded":
                    packet.decoded,
            },
        )

    def _on_mavlink_error(
        self,
        message: str,
    ) -> None:
        self.mavlink_panel.show_error(
            message
        )
        self.event_bus.publish(
            "MAVLINK",
            "ERROR",
            {
                "message":
                    message,
            },
        )

    def _on_mavlink_reader_finished(
        self,
    ) -> None:
        self.mavlink_reader = None

        self.mavlink_panel.set_connection(
            False,
            "Disconnected",
        )

    # -------- SDR --------

    def _refresh_sdr_devices(
        self,
    ) -> None:
        status = uhd_backend_status()

        if not status[
            "uhd_find_devices"
        ]:
            self.sdr_panel.set_devices([])
            self.sdr_panel.set_backend_status(
                "UHD discovery tool not installed"
            )
            return

        if not status[
            "rx_samples_to_file"
        ]:
            self.sdr_panel.set_backend_status(
                "UHD found; RX capture utility missing"
            )
        else:
            self.sdr_panel.set_backend_status(
                "UHD ready; scanning..."
            )

        try:
            devices = discover_uhd_devices()
            self.sdr_panel.set_devices(
                devices
            )

            if devices:
                self.sdr_panel.set_backend_status(
                    f"Detected {len(devices)} USRP device(s)"
                )
            else:
                self.sdr_panel.set_backend_status(
                    "UHD ready; no USRP detected"
                )

            self.event_bus.publish(
                "SDR",
                "DEVICE_SCAN",
                {
                    "count":
                        len(devices),
                    "devices":
                        [
                            device.display_name
                            for device in devices
                        ],
                },
            )

        except Exception as exc:
            self.sdr_panel.set_devices([])
            self.sdr_panel.show_error(
                str(exc)
            )

    def _start_sdr_capture(
        self,
        capture_settings: dict,
    ) -> None:
        if (
            self.sdr_worker is not None
            and self.sdr_worker.isRunning()
        ):
            return

        if not uhd_backend_status()[
            "ready"
        ]:
            self.sdr_panel.show_error(
                "UHD capture backend is not ready."
            )
            return

        experiment_id = (
            self.database_writer.active_experiment_id
        )

        if not experiment_id:
            QMessageBox.information(
                self,
                "SDR Capture",
                (
                    "Start an experiment before "
                    "starting IQ capture."
                ),
            )
            return

        utc_tag = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )

        iq_path = (
            self.settings.iq_directory
            / experiment_id
            / (
                f"usrp_915MHz_{utc_tag}_"
                "ch0.sc16"
            )
        )

        config = SdrCaptureConfig(
            device_args=str(
                capture_settings.get(
                    "device_args",
                    "",
                )
            ),
            file_path=iq_path,
            center_frequency_hz=int(
                capture_settings[
                    "center_frequency_hz"
                ]
            ),
            sample_rate_hz=int(
                capture_settings[
                    "sample_rate_hz"
                ]
            ),
            gain_db=float(
                capture_settings[
                    "gain_db"
                ]
            ),
        )

        worker = SdrCaptureWorker(
            config=config,
            parent=self,
        )

        worker.capture_started.connect(
            self._on_sdr_capture_started
        )
        worker.capture_stopped.connect(
            self._on_sdr_capture_stopped
        )
        worker.output_line.connect(
            self.sdr_panel.append_output
        )
        worker.error_occurred.connect(
            self._on_sdr_error
        )
        worker.finished.connect(
            self._on_sdr_worker_finished
        )

        self.sdr_worker = worker

        self.sdr_panel.set_capture_active(
            True,
            str(iq_path),
        )

        worker.start()

    def _stop_sdr_capture(
        self,
    ) -> None:
        worker = self.sdr_worker

        if worker is None:
            return

        if worker.isRunning():
            worker.stop()

    def _on_sdr_capture_started(
        self,
        payload: dict,
    ) -> None:
        self.event_bus.publish(
            "SDR",
            "CAPTURE_START",
            {
                "center_frequency_hz":
                    payload[
                        "center_frequency_hz"
                    ],
                "sample_rate_hz":
                    payload[
                        "sample_rate_hz"
                    ],
                "gain_db":
                    payload["gain_db"],
                "iq_file":
                    payload["file"],
                "device_args":
                    payload[
                        "device_args"
                    ],
                "channel":
                    payload["channel"],
                "sample_type":
                    payload[
                        "sample_type"
                    ],
                "synchronization":
                    "software_event_timestamp",
            },
        )

    def _on_sdr_capture_stopped(
        self,
        payload: dict,
    ) -> None:
        self.event_bus.publish(
            "SDR",
            "CAPTURE_STOP",
            {
                "iq_file":
                    payload["file"],
                "file_size_bytes":
                    payload[
                        "file_size_bytes"
                    ],
                "return_code":
                    payload[
                        "return_code"
                    ],
                "synchronization":
                    "software_event_timestamp",
            },
        )

        self.sdr_panel.set_capture_active(
            False,
            payload["file"],
        )

        if self._experiment_stop_pending:
            self._complete_experiment()

    def _on_sdr_error(
        self,
        message: str,
    ) -> None:
        self.sdr_panel.show_error(
            message
        )
        self.event_bus.publish(
            "SDR",
            "ERROR",
            {
                "message":
                    message,
            },
        )

    def _on_sdr_worker_finished(
        self,
    ) -> None:
        self.sdr_worker = None

        # A worker can fail before emitting capture_stopped. Do not leave an
        # operator-requested experiment stop waiting forever in that case.
        if self._experiment_stop_pending:
            self._complete_experiment()

    # -------- Experiment --------

    def _open_session_review(
        self,
    ) -> None:
        dialog = SessionReviewDialog(
            settings=self.settings,
            parent=self,
        )
        dialog.exec()

    def _start_experiment(
        self,
        metadata: dict,
    ) -> None:
        start_timestamp = MasterClock.now()

        try:
            experiment_id = (
                self.database_writer.start_experiment(
                    metadata,
                    start_timestamp,
                )
            )
        except RuntimeError as exc:
            QMessageBox.warning(
                self,
                "Experiment",
                str(exc),
            )
            return

        self.guided_trial_panel.set_recording(
            True,
            reset=True,
        )

        try:
            package = create_experiment_package(
                experiment_root=(
                    self.settings.experiment_directory
                ),
                export_root=(
                    self.settings.export_directory
                ),
                iq_root=self.settings.iq_directory,
                experiment_id=experiment_id,
                metadata=metadata,
                timestamp=start_timestamp,
                application_name=(
                    self.settings.application_name
                ),
                application_version=(
                    self.settings.version
                ),
                database_path=(
                    self.settings.database_path
                ),
                controller_mapping=asdict(
                    self.controller_mapping
                ),
                mavlink_configuration={
                    "port": (
                        self.mavlink_panel.current_port()
                    ),
                    "baud": (
                        self.mavlink_panel.current_baud()
                    ),
                    "connected": bool(
                        self.mavlink_reader is not None
                        and self.mavlink_reader.isRunning()
                    ),
                    "direction": "receive_only",
                },
                sdr_configuration={
                    **self.sdr_panel.capture_settings(),
                    "auto_capture": (
                        self.sdr_panel.auto_capture_enabled()
                    ),
                    "capture_backend": (
                        uhd_backend_status().get(
                            "rx_samples_to_file"
                        )
                    ),
                    "direction": "receive_only",
                },
                guided_trial_configuration={
                    "actions": list(GUIDED_ACTIONS),
                    "target_repetitions": (
                        self.guided_trial_panel.target_repetitions
                    ),
                    "labeling": "START_END_INTERVALS",
                },
            )
            self._experiment_packages[
                experiment_id
            ] = package
        except Exception as exc:
            self.logger.exception(
                "Could not create package for experiment %s",
                experiment_id,
            )
            QMessageBox.warning(
                self,
                "Experiment Packaging",
                (
                    "The experiment is recording in SQLite, but "
                    "its package directory could not be created:\n\n"
                    f"{exc}"
                ),
            )

        self.toolbar_start_action.setEnabled(
            False
        )
        self.toolbar_stop_action.setEnabled(
            True
        )
        self.toolbar_mark_action.setEnabled(
            True
        )

        self.statusBar().showMessage(
            (
                f"RECORDING | "
                f"{metadata.get('name', 'Experiment')} | "
                f"Session {experiment_id[:8]} | "
                f"{self.settings.database_path}"
            )
        )

        self.event_bus.publish(
            "EXPERIMENT",
            "START",
            {
                **metadata,
                "experiment_id":
                    experiment_id,
            },
        )

        if (
            self.sdr_panel.auto_capture_enabled()
            and self.sdr_panel.current_device_args()
            is not None
        ):
            self._start_sdr_capture(
                self.sdr_panel.capture_settings()
            )

    def _stop_experiment(
        self,
    ) -> None:
        if (
            not self.database_writer.is_recording
            or self._experiment_stop_pending
        ):
            return

        self.guided_trial_panel.end_active_trial(
            automatic=True
        )
        self.guided_trial_panel.set_recording(
            False
        )

        if (
            self.sdr_worker is not None
            and self.sdr_worker.isRunning()
        ):
            self._experiment_stop_pending = True
            self.experiment_panel.start_button.setEnabled(
                False
            )
            self.experiment_panel.stop_button.setEnabled(
                False
            )
            self.experiment_panel.marker_button.setEnabled(
                False
            )
            self.toolbar_start_action.setEnabled(
                False
            )
            self.toolbar_stop_action.setEnabled(
                False
            )
            self.toolbar_mark_action.setEnabled(
                False
            )
            self.statusBar().showMessage(
                "Stopping SDR capture before saving experiment..."
            )
            self._stop_sdr_capture()
            return

        self._complete_experiment()

    def _complete_experiment(
        self,
    ) -> None:
        """Close the active experiment after acquisition has stopped."""
        if not self.database_writer.is_recording:
            self._experiment_stop_pending = False
            return

        self.event_bus.publish(
            "EXPERIMENT",
            "STOP",
            {
                "experiment_id":
                    self.database_writer.active_experiment_id
            },
        )

        completed_id = (
            self.database_writer.stop_experiment(
                MasterClock.now()
            )
        )
        self._experiment_stop_pending = False
        self.guided_trial_panel.set_recording(
            False
        )

        self.experiment_panel.start_button.setEnabled(
            True
        )
        self.experiment_panel.stop_button.setEnabled(
            False
        )
        self.experiment_panel.marker_button.setEnabled(
            False
        )
        self.toolbar_start_action.setEnabled(
            True
        )
        self.toolbar_stop_action.setEnabled(
            False
        )
        self.toolbar_mark_action.setEnabled(
            False
        )

        self.statusBar().showMessage(
            (
                f"Finalizing experiment "
                f"{completed_id[:8] if completed_id else '—'} "
                "and preparing exports..."
            )
        )

    def _on_database_experiment_closed(
        self,
        experiment_id: str,
    ) -> None:
        """Start exports only after SQLite commits the completed session."""
        package = self._experiment_packages.get(
            experiment_id
        )

        if package is None:
            message = (
                "SQLite saved experiment "
                f"{experiment_id[:8]}, but no package was available "
                "for automatic export."
            )
            self.logger.error(message)
            if not self.database_writer.is_recording:
                self.statusBar().showMessage(message)
            return

        worker = ExperimentExportWorker(
            database_path=self.settings.database_path,
            package=package,
            parent=self,
        )
        worker.export_completed.connect(
            self._on_export_completed
        )
        worker.export_failed.connect(
            self._on_export_failed
        )
        worker.finished.connect(
            lambda experiment_id=experiment_id:
                self._on_export_worker_finished(
                    experiment_id
                )
        )

        self._export_workers[experiment_id] = worker
        self.logger.info(
            "Exporting completed experiment %s to %s",
            experiment_id,
            package.export_directory,
        )
        worker.start()

    def _on_export_completed(
        self,
        result: dict,
    ) -> None:
        experiment_id = str(
            result["experiment_id"]
        )
        export_directory = str(
            result["export_directory"]
        )
        self.logger.info(
            "Experiment export complete: %s -> %s",
            experiment_id,
            export_directory,
        )

        if not self.database_writer.is_recording:
            self.statusBar().showMessage(
                "Experiment saved and exported to "
                f"{export_directory}"
            )

    def _on_export_failed(
        self,
        experiment_id: str,
        message: str,
    ) -> None:
        self.logger.error(
            "Experiment export failed for %s: %s",
            experiment_id,
            message,
        )

        if not self.database_writer.is_recording:
            self.statusBar().showMessage(
                "Experiment saved to SQLite; automatic export failed."
            )

        QMessageBox.warning(
            self,
            "Experiment Export",
            (
                "The experiment remains safely stored in SQLite, "
                "but its automatic export failed:\n\n"
                f"{message}"
            ),
        )

    def _on_export_worker_finished(
        self,
        experiment_id: str,
    ) -> None:
        worker = self._export_workers.pop(
            experiment_id,
            None,
        )
        if worker is not None:
            worker.deleteLater()
        self._experiment_packages.pop(
            experiment_id,
            None,
        )

    def _on_database_command_failed(
        self,
        command: str,
        message: str,
    ) -> None:
        self.logger.error(
            "Database command failed (%s): %s",
            command,
            message,
        )
        self.statusBar().showMessage(
            f"Database error during {command}: {message}"
        )

    def _mark_event(
        self,
        label: str,
    ) -> None:
        if not self.database_writer.is_recording:
            QMessageBox.information(
                self,
                "Mark Event",
                (
                    "Start an experiment before "
                    "creating markers."
                ),
            )
            return

        self.event_bus.publish(
            "OPERATOR",
            "MARKER",
            {
                "label":
                    label,
                "experiment_id":
                    self.database_writer.active_experiment_id,
            },
        )

    def _start_guided_trial(
        self,
        action: str,
        trial_number: int,
    ) -> None:
        if not self.database_writer.is_recording:
            return

        self.event_bus.publish(
            "OPERATOR",
            "ACTION_START",
            {
                "label": f"{action}_START",
                "action": action,
                "phase": "START",
                "trial_number": trial_number,
                "target_repetitions": (
                    self.guided_trial_panel.target_repetitions
                ),
                "experiment_id": (
                    self.database_writer.active_experiment_id
                ),
            },
        )

    def _end_guided_trial(
        self,
        action: str,
        trial_number: int,
        automatic: bool,
    ) -> None:
        if not self.database_writer.is_recording:
            return

        self.event_bus.publish(
            "OPERATOR",
            "ACTION_END",
            {
                "label": f"{action}_END",
                "action": action,
                "phase": "END",
                "trial_number": trial_number,
                "target_repetitions": (
                    self.guided_trial_panel.target_repetitions
                ),
                "automatic": automatic,
                "experiment_id": (
                    self.database_writer.active_experiment_id
                ),
            },
        )

    # -------- Unified timeline --------

    def _on_event(
        self,
        event: DcmfEvent,
    ) -> None:
        if (
            event.source == "CONTROLLER"
            and event.kind == "SAMPLE"
        ):
            self._controller_sample_number += 1

            self.dataset_panel.controller_count.setText(
                str(
                    self._controller_sample_number
                )
            )

            if (
                self._controller_sample_number
                % 10
                != 0
            ):
                return

            mapped = event.payload.get(
                "mapped",
                {},
            )

            description = (
                " ".join(
                    (
                        f"{name}="
                        f"{value:+.3f}"
                        if value is not None
                        else f"{name}=—"
                    )
                    for name, value
                    in mapped.items()
                )
            )

        elif (
            event.source == "MAVLINK"
            and event.kind == "MESSAGE"
        ):
            self.dataset_panel.mavlink_count.setText(
                str(
                    self._mavlink_message_number
                )
            )

            description = (
                f"RX {event.payload.get('message_name')} "
                f"sys={event.payload.get('system_id')} "
                f"comp={event.payload.get('component_id')}"
            )

        elif (
            event.source == "SDR"
            and event.kind.startswith(
                "CAPTURE_"
            )
        ):
            self._sdr_record_number += 1

            self.dataset_panel.sdr_count.setText(
                str(
                    self._sdr_record_number
                )
            )

            description = (
                f"{event.kind}: "
                f"{event.payload.get('iq_file', '')}"
            )

        elif (
            event.source == "OPERATOR"
            and event.kind in {
                "ACTION_START",
                "ACTION_END",
            }
        ):
            description = (
                f"{event.payload.get('label', event.kind)} | "
                f"trial {event.payload.get('trial_number', '—')}"
            )
            if event.payload.get("automatic"):
                description += " | automatically closed"

        else:
            description = (
                f"{event.kind}: "
                f"{event.payload}"
            )

        self.timeline_panel.add_row(
            event.timestamp.monotonic_seconds,
            event.timestamp.utc_iso,
            event.source,
            description,
        )

        if event.source in {
            "EXPERIMENT",
            "OPERATOR",
        }:
            count = (
                int(
                    self.dataset_panel.event_count.text()
                )
                + 1
            )

            self.dataset_panel.event_count.setText(
                str(count)
            )

    def _show_about(
        self,
    ) -> None:
        QMessageBox.about(
            self,
            "About DCMF",
            (
                "<b>Drone Control Mapping Framework</b><br>"
                f"Version {self.settings.version}<br><br>"
                "Synchronized receive-only acquisition "
                "and experiment recording for controller, "
                "MAVLink/RFD900, SDR IQ, and operator events."
            ),
        )

    def closeEvent(
        self,
        event,
    ) -> None:
        closing_experiment_id: str | None = None

        if self.database_writer.is_recording:
            self.guided_trial_panel.end_active_trial(
                automatic=True
            )

        if (
            self.sdr_worker is not None
            and self.sdr_worker.isRunning()
        ):
            self.sdr_worker.stop()

        if self.database_writer.is_recording:
            self.event_bus.publish(
                "SYSTEM",
                "APPLICATION_CLOSING",
                {
                    "reason":
                        "Window closed during recording"
                },
            )

            closing_experiment_id = (
                self.database_writer.stop_experiment(
                    MasterClock.now()
                )
            )

        if self.controller_reader.isRunning():
            self.controller_reader.stop()

        if (
            self.mavlink_reader is not None
            and self.mavlink_reader.isRunning()
        ):
            self.mavlink_reader.stop()

        self.database_writer.shutdown()

        # The Qt event loop is closing, so a queued experiment_closed signal
        # may not be delivered. Export this final session synchronously after
        # the database writer has committed and shut down.
        if closing_experiment_id is not None:
            package = self._experiment_packages.pop(
                closing_experiment_id,
                None,
            )
            if package is not None:
                try:
                    result = export_experiment(
                        self.settings.database_path,
                        package,
                    )
                    self.logger.info(
                        "Experiment export complete during shutdown: "
                        "%s -> %s",
                        closing_experiment_id,
                        result["export_directory"],
                    )
                except Exception:
                    self.logger.exception(
                        "Experiment export failed during shutdown: %s",
                        closing_experiment_id,
                    )

        unfinished_exports = []
        for experiment_id, worker in list(
            self._export_workers.items()
        ):
            if worker.isRunning() and not worker.wait(
                30_000
            ):
                unfinished_exports.append(
                    experiment_id
                )

        if unfinished_exports:
            self.logger.warning(
                "Waiting for experiment exports before closing: %s",
                ", ".join(unfinished_exports),
            )
            event.ignore()
            return

        event.accept()

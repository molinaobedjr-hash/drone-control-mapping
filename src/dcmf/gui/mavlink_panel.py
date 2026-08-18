"""Telemetry-radio/MAVLink connection and live-message panel."""

from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dcmf.acquisition.mavlink.reader import SerialPortInfo


class MavlinkPanel(QWidget):
    """User controls and status for MAVLink capture and guarded output."""

    connect_requested = Signal(str, int)
    disconnect_requested = Signal()
    refresh_requested = Signal()
    output_enabled_changed = Signal(bool)

    def __init__(
        self,
        default_baud: int = 57600,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._ports: list[SerialPortInfo] = []

        self.status_label = QLabel("Disconnected")
        self.heartbeat_label = QLabel("Not observed")
        self.last_message_label = QLabel("—")
        self.message_count_label = QLabel("0")
        self.vehicle_label = QLabel("Not observed")
        self.output_status_label = QLabel("Output disabled")
        self.output_status_label.setWordWrap(True)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(230)

        self.refresh_button = QPushButton("Refresh")

        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_button)

        self.baud_combo = QComboBox()
        for baud in (
            57600,
            115200,
            230400,
            460800,
            921600,
        ):
            self.baud_combo.addItem(str(baud), baud)

        index = self.baud_combo.findData(default_baud)
        if index >= 0:
            self.baud_combo.setCurrentIndex(index)

        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)

        connect_row = QHBoxLayout()
        connect_row.addWidget(self.connect_button)
        connect_row.addWidget(self.disconnect_button)

        self.output_checkbox = QCheckBox(
            "Transmit mapped MANUAL_CONTROL (disarmed tests only)"
        )
        self.output_checkbox.setEnabled(False)
        self.output_checkbox.setToolTip(
            "Opt-in 20 Hz MAVLink output. Requires a complete DCMF mapping, "
            "an active experiment, a live controller, and a vehicle heartbeat. "
            "DCMF suppresses this output while the vehicle reports ARMED."
        )

        form = QFormLayout()
        form.addRow("Status", self.status_label)
        form.addRow("Serial Port", port_row)
        form.addRow("Baud", self.baud_combo)
        form.addRow("Heartbeat", self.heartbeat_label)
        form.addRow("Vehicle", self.vehicle_label)
        form.addRow("Last Message", self.last_message_label)
        form.addRow("Messages", self.message_count_label)
        form.addRow("Control Output", self.output_status_label)

        self.message_view = QPlainTextEdit()
        self.message_view.setReadOnly(True)
        self.message_view.setMaximumBlockCount(400)
        self.message_view.setPlaceholderText(
            "Decoded inbound and locally transmitted MAVLink messages "
            "will appear here."
        )

        group = QGroupBox("915 MHz Telemetry Radio / MAVLink")
        group_layout = QVBoxLayout(group)
        group_layout.addLayout(form)
        group_layout.addLayout(connect_row)
        group_layout.addWidget(self.output_checkbox)
        group_layout.addWidget(self.message_view)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

        self.refresh_button.clicked.connect(
            self.refresh_requested.emit
        )
        self.connect_button.clicked.connect(
            self._emit_connect
        )
        self.disconnect_button.clicked.connect(
            self.disconnect_requested.emit
        )
        self.output_checkbox.toggled.connect(
            self.output_enabled_changed.emit
        )

    def set_ports(
        self,
        ports: list[SerialPortInfo],
    ) -> None:
        """Replace the serial-port selector contents."""
        current_device = self.current_port()
        self._ports = ports

        self.port_combo.blockSignals(True)
        self.port_combo.clear()

        if not ports:
            self.port_combo.addItem(
                "No serial devices found",
                None,
            )

        else:
            for port in ports:
                self.port_combo.addItem(
                    port.display_name,
                    port.device,
                )

            if current_device:
                index = self.port_combo.findData(
                    current_device
                )
                if index >= 0:
                    self.port_combo.setCurrentIndex(
                        index
                    )

        self.port_combo.blockSignals(False)
        self.connect_button.setEnabled(
            bool(ports)
        )

    def current_port(self) -> str | None:
        value = self.port_combo.currentData()
        return str(value) if value else None

    def current_baud(self) -> int:
        return int(self.baud_combo.currentData())

    def set_connection(
        self,
        connected: bool,
        description: str,
    ) -> None:
        self.status_label.setText(description)
        self.connect_button.setEnabled(
            not connected and bool(self._ports)
        )
        self.disconnect_button.setEnabled(
            connected
        )
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.refresh_button.setEnabled(not connected)
        self.output_checkbox.setEnabled(connected)

        if not connected:
            self.heartbeat_label.setText(
                "Not observed"
            )
            self.vehicle_label.setText("Not observed")
            self.set_output_checked(False)
            self.set_output_status("Output disabled")

    def set_output_checked(self, enabled: bool) -> None:
        """Set the opt-in checkbox without recursively emitting a request."""
        self.output_checkbox.blockSignals(True)
        self.output_checkbox.setChecked(bool(enabled))
        self.output_checkbox.blockSignals(False)

    def set_output_status(self, message: str) -> None:
        self.output_status_label.setText(message)

    def set_vehicle_state(
        self,
        system_id: int | None,
        component_id: int | None,
        armed: bool | None,
    ) -> None:
        state = "ARMED" if armed else "DISARMED"
        if armed is None:
            state = "state unknown"
        self.vehicle_label.setText(
            f"SYS {system_id} / COMP {component_id} — {state}"
        )

    def set_message_count(self, count: int) -> None:
        self.message_count_label.setText(str(count))

    def add_packet(
        self,
        message_name: str,
        system_id: int | None,
        component_id: int | None,
        decoded: dict,
        direction: str = "RX",
    ) -> None:
        self.last_message_label.setText(message_name)

        if message_name == "HEARTBEAT":
            self.heartbeat_label.setText(
                f"SYS {system_id} / COMP {component_id}"
            )

        compact = json.dumps(
            decoded,
            separators=(",", ":"),
            default=str,
        )

        self.message_view.appendPlainText(
            (
                f"{direction} {message_name} "
                f"[sys={system_id}, comp={component_id}] "
                f"{compact}"
            )
        )

    def show_error(self, message: str) -> None:
        self.status_label.setText(
            f"Error: {message}"
        )

    def _emit_connect(self) -> None:
        port = self.current_port()
        if not port:
            return

        self.connect_requested.emit(
            port,
            self.current_baud(),
        )

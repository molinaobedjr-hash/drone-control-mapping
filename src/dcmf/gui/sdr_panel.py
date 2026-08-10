"""USRP/UHD SDR discovery and IQ capture controls."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dcmf.acquisition.sdr.reader import UhdDevice


class SdrPanel(QWidget):
    """Receive-only SDR configuration/status panel."""

    refresh_requested = Signal()
    start_capture_requested = Signal(dict)
    stop_capture_requested = Signal()

    def __init__(
        self,
        center_hz: int,
        sample_rate_hz: int,
        gain_db: float = 30.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._devices: list[UhdDevice] = []

        self.status_label = QLabel("UHD not checked")
        self.file_label = QLabel("—")
        self.file_label.setWordWrap(True)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(220)
        self.refresh_button = QPushButton("Refresh")

        device_row = QHBoxLayout()
        device_row.addWidget(self.device_combo, 1)
        device_row.addWidget(self.refresh_button)

        self.frequency_spin = QDoubleSpinBox()
        self.frequency_spin.setRange(
            1.0,
            6000.0,
        )
        self.frequency_spin.setDecimals(3)
        self.frequency_spin.setSuffix(" MHz")
        self.frequency_spin.setValue(
            center_hz / 1_000_000
        )

        self.sample_rate_spin = QDoubleSpinBox()
        self.sample_rate_spin.setRange(
            0.100,
            60.000,
        )
        self.sample_rate_spin.setDecimals(3)
        self.sample_rate_spin.setSuffix(" MS/s")
        self.sample_rate_spin.setValue(
            sample_rate_hz / 1_000_000
        )

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(
            0.0,
            100.0,
        )
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setValue(gain_db)

        self.auto_capture_checkbox = QCheckBox(
            "Start/stop IQ capture with experiment"
        )
        self.auto_capture_checkbox.setChecked(True)

        self.start_button = QPushButton(
            "Start IQ Capture"
        )
        self.stop_button = QPushButton(
            "Stop Capture"
        )
        self.stop_button.setEnabled(False)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)

        form = QFormLayout()
        form.addRow("Status", self.status_label)
        form.addRow("USRP", device_row)
        form.addRow(
            "Center Frequency",
            self.frequency_spin,
        )
        form.addRow(
            "Sample Rate",
            self.sample_rate_spin,
        )
        form.addRow("Gain", self.gain_spin)
        form.addRow("IQ File", self.file_label)

        self.output_view = QPlainTextEdit()
        self.output_view.setReadOnly(True)
        self.output_view.setMaximumBlockCount(250)
        self.output_view.setMaximumHeight(100)
        self.output_view.setPlaceholderText(
            "UHD capture status will appear here."
        )

        group = QGroupBox(
            "SDR / USRP — Receive Only (Software Sync)"
        )
        gl = QVBoxLayout(group)
        gl.addLayout(form)
        gl.addWidget(self.auto_capture_checkbox)
        gl.addLayout(button_row)
        gl.addWidget(self.output_view)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

        self.refresh_button.clicked.connect(
            self.refresh_requested.emit
        )
        self.start_button.clicked.connect(
            self._emit_start
        )
        self.stop_button.clicked.connect(
            self.stop_capture_requested.emit
        )

    def set_devices(
        self,
        devices: list[UhdDevice],
    ) -> None:
        current_args = self.current_device_args()
        self._devices = devices

        self.device_combo.clear()

        if not devices:
            self.device_combo.addItem(
                "No USRP detected",
                None,
            )
        else:
            for device in devices:
                self.device_combo.addItem(
                    device.display_name,
                    device.device_args,
                )

            if current_args is not None:
                index = self.device_combo.findData(
                    current_args
                )
                if index >= 0:
                    self.device_combo.setCurrentIndex(
                        index
                    )

        self.start_button.setEnabled(
            bool(devices)
        )

    def current_device_args(self) -> str | None:
        value = self.device_combo.currentData()

        if value is None:
            return None

        return str(value)

    def capture_settings(self) -> dict:
        return {
            "device_args":
                self.current_device_args() or "",
            "center_frequency_hz": int(
                self.frequency_spin.value()
                * 1_000_000
            ),
            "sample_rate_hz": int(
                self.sample_rate_spin.value()
                * 1_000_000
            ),
            "gain_db":
                float(self.gain_spin.value()),
        }

    def auto_capture_enabled(self) -> bool:
        return self.auto_capture_checkbox.isChecked()

    def set_backend_status(
        self,
        text: str,
    ) -> None:
        self.status_label.setText(text)

    def set_capture_active(
        self,
        active: bool,
        file_path: str = "",
    ) -> None:
        self.start_button.setEnabled(
            not active and bool(self._devices)
        )
        self.stop_button.setEnabled(active)

        self.device_combo.setEnabled(not active)
        self.frequency_spin.setEnabled(not active)
        self.sample_rate_spin.setEnabled(
            not active
        )
        self.gain_spin.setEnabled(not active)
        self.refresh_button.setEnabled(not active)

        if active:
            self.status_label.setText("Capturing IQ")
            self.file_label.setText(file_path)

    def append_output(
        self,
        line: str,
    ) -> None:
        self.output_view.appendPlainText(line)

    def show_error(
        self,
        message: str,
    ) -> None:
        self.status_label.setText(
            f"Error: {message}"
        )
        self.output_view.appendPlainText(message)

    def _emit_start(self) -> None:
        if not self._devices:
            return

        self.start_capture_requested.emit(
            self.capture_settings()
        )

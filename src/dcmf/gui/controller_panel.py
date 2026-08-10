"""Live TX16S USB controller panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dcmf.acquisition.controller.mapping import (
    ControllerMapping,
)


class ControllerPanel(QWidget):
    """Shows raw USB axes and mapped flight controls."""

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.mapping = ControllerMapping()

        self.status_label = QLabel(
            "Scanning for USB joystick..."
        )
        self.device_label = QLabel("—")
        self.device_label.setWordWrap(True)

        info = QFormLayout()
        info.addRow("Status", self.status_label)
        info.addRow("Device", self.device_label)

        self.mapped_bars: dict[
            str,
            QProgressBar
        ] = {}

        mapped_group = QGroupBox(
            "Mapped Flight Controls"
        )
        mapped_form = QFormLayout(
            mapped_group
        )

        for control in (
            "roll",
            "pitch",
            "yaw",
            "throttle",
        ):
            bar = QProgressBar()
            bar.setRange(-1000, 1000)
            bar.setValue(0)
            bar.setFormat("Not mapped")
            self.mapped_bars[control] = bar

            mapped_form.addRow(
                control.capitalize(),
                bar,
            )

        self.mapping_status_label = QLabel(
            "Controller not calibrated"
        )
        self.mapping_status_label.setWordWrap(True)

        self.axis_container = QWidget()
        self.axis_form = QFormLayout(
            self.axis_container
        )
        self.axis_bars: list[
            QProgressBar
        ] = []

        raw_scroll = QScrollArea()
        raw_scroll.setWidgetResizable(True)
        raw_scroll.setWidget(
            self.axis_container
        )
        raw_scroll.setMinimumHeight(150)

        self.buttons_label = QLabel(
            "No button data"
        )
        self.buttons_label.setWordWrap(True)

        group = QGroupBox(
            "TX16S Controller — Raw USB Input"
        )
        gl = QVBoxLayout(group)
        gl.addLayout(info)
        gl.addWidget(
            self.mapping_status_label
        )
        gl.addWidget(mapped_group)
        gl.addWidget(
            QLabel("Raw USB Axes")
        )
        gl.addWidget(raw_scroll)
        gl.addWidget(
            QLabel("Pressed Buttons")
        )
        gl.addWidget(self.buttons_label)

        layout = QVBoxLayout(self)
        layout.addWidget(group)

    def set_mapping(
        self,
        mapping: ControllerMapping,
    ) -> None:
        self.mapping = mapping

        assigned = []

        for control in (
            "roll",
            "pitch",
            "yaw",
            "throttle",
        ):
            item = getattr(
                mapping,
                control,
            )

            if item is not None:
                suffix = (
                    " inverted"
                    if item.inverted
                    else ""
                )
                assigned.append(
                    f"{control}=Axis "
                    f"{item.axis_index}{suffix}"
                )

        if assigned:
            self.mapping_status_label.setText(
                " | ".join(assigned)
            )
        else:
            self.mapping_status_label.setText(
                "Controller not calibrated"
            )

    def set_connection(
        self,
        connected: bool,
        description: str,
    ) -> None:
        self.status_label.setText(
            "Connected"
            if connected
            else "Disconnected"
        )
        self.device_label.setText(
            description
        )

    def set_sample(
        self,
        axes: tuple[float, ...],
        buttons: tuple[int, ...],
        hats: tuple[
            tuple[int, int],
            ...
        ],
    ) -> None:
        self._ensure_axis_count(
            len(axes)
        )

        for index, value in enumerate(axes):
            scaled = int(
                max(
                    -1.0,
                    min(1.0, value),
                )
                * 1000
            )

            bar = self.axis_bars[index]
            bar.setValue(scaled)
            bar.setFormat(
                f"{value:+.3f}"
            )

        for control, bar in (
            self.mapped_bars.items()
        ):
            value = self.mapping.map_value(
                control,
                axes,
            )

            if value is None:
                bar.setValue(0)
                bar.setFormat(
                    "Not mapped"
                )
                continue

            bar.setValue(
                int(value * 1000)
            )
            bar.setFormat(
                f"{value:+.3f}"
            )

        pressed = [
            str(index)
            for index, value
            in enumerate(buttons)
            if value
        ]

        text = (
            ", ".join(pressed)
            if pressed
            else "None"
        )

        if hats:
            text += (
                " | Hats: "
                + ", ".join(
                    f"{index}:{value}"
                    for index, value
                    in enumerate(hats)
                )
            )

        self.buttons_label.setText(
            text
        )

    def _ensure_axis_count(
        self,
        count: int,
    ) -> None:
        while (
            len(self.axis_bars)
            < count
        ):
            index = len(
                self.axis_bars
            )

            bar = QProgressBar()
            bar.setRange(
                -1000,
                1000,
            )
            bar.setValue(0)
            bar.setFormat("+0.000")

            self.axis_bars.append(bar)
            self.axis_form.addRow(
                f"Axis {index}",
                bar,
            )

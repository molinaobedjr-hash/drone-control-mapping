"""Interactive TX16S axis-learning dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from dcmf.acquisition.controller.mapping import (
    AxisMapping,
    ControllerMapping,
    CONTROL_NAMES,
)


DISPLAY_NAMES = {
    "roll": "Roll",
    "pitch": "Pitch",
    "yaw": "Yaw",
    "throttle": "Throttle",
}


class ControllerCalibrationDialog(QDialog):
    """Learns which raw USB joystick axis belongs to each flight control."""

    MOVEMENT_THRESHOLD = 0.35

    def __init__(
        self,
        mapping: ControllerMapping,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(
            "TX16S Controller Calibration"
        )
        self.setMinimumWidth(620)

        self.mapping = mapping
        self.latest_axes: tuple[float, ...] = ()
        self.baseline_axes: tuple[float, ...] = ()
        self.learning_control: str | None = None

        intro = QLabel(
            "1. Connect the TX16S in USB joystick/HID mode.\n"
            "2. Leave the controls still and click Capture Baseline.\n"
            "3. Click Learn beside one control, then move only that "
            "stick axis strongly.\n"
            "4. Repeat for Roll, Pitch, Yaw, and Throttle, then Save."
        )
        intro.setWordWrap(True)

        self.device_status = QLabel(
            "Waiting for controller samples..."
        )

        self.baseline_button = QPushButton(
            "Capture Baseline"
        )
        self.baseline_button.clicked.connect(
            self._capture_baseline
        )

        self.raw_axes_label = QLabel("No axis data")
        self.raw_axes_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.mapping_labels: dict[str, QLabel] = {}
        self.invert_checks: dict[str, QCheckBox] = {}
        self.learn_buttons: dict[str, QPushButton] = {}

        mapping_group = QGroupBox("Control Mapping")
        form = QFormLayout(mapping_group)

        for control in CONTROL_NAMES:
            label = QLabel()
            invert = QCheckBox("Invert")
            learn = QPushButton(
                f"Learn {DISPLAY_NAMES[control]}"
            )
            learn.clicked.connect(
                lambda checked=False, name=control:
                    self._start_learning(name)
            )

            row = QHBoxLayout()
            row.addWidget(label, 1)
            row.addWidget(invert)
            row.addWidget(learn)

            form.addRow(
                DISPLAY_NAMES[control],
                row,
            )

            self.mapping_labels[control] = label
            self.invert_checks[control] = invert
            self.learn_buttons[control] = learn

        self.learning_label = QLabel("Not learning")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(
            self._accept_mapping
        )
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.device_status)
        layout.addWidget(self.baseline_button)
        layout.addWidget(QLabel("Live raw axes"))
        layout.addWidget(self.raw_axes_label)
        layout.addWidget(mapping_group)
        layout.addWidget(self.learning_label)
        layout.addWidget(buttons)

        self._load_existing_mapping()

    def update_controller_sample(
        self,
        axes: tuple[float, ...],
    ) -> None:
        """Receive the newest live axes from MainWindow."""
        self.latest_axes = tuple(
            float(value)
            for value in axes
        )

        self.device_status.setText(
            f"Receiving {len(axes)} axes"
        )

        self.raw_axes_label.setText(
            "   ".join(
                f"Axis {index}: {value:+.3f}"
                for index, value in enumerate(axes)
            )
        )

        if (
            self.learning_control is not None
            and self.baseline_axes
        ):
            self._try_detect_axis()

    def _capture_baseline(self) -> None:
        if not self.latest_axes:
            QMessageBox.information(
                self,
                "Calibration",
                "No controller axis samples are available yet.",
            )
            return

        self.baseline_axes = self.latest_axes
        self.learning_control = None

        self.learning_label.setText(
            "Baseline captured. Select a control to learn."
        )

    def _start_learning(
        self,
        control: str,
    ) -> None:
        if not self.latest_axes:
            QMessageBox.information(
                self,
                "Calibration",
                "Connect the TX16S first.",
            )
            return

        # Capture a fresh baseline immediately before each learning action.
        self.baseline_axes = self.latest_axes
        self.learning_control = control

        self.learning_label.setText(
            f"Learning {DISPLAY_NAMES[control]}: "
            "move ONLY that control strongly now."
        )

    def _try_detect_axis(self) -> None:
        count = min(
            len(self.latest_axes),
            len(self.baseline_axes),
        )

        if count == 0:
            return

        deltas = [
            abs(
                self.latest_axes[index]
                - self.baseline_axes[index]
            )
            for index in range(count)
        ]

        axis_index = max(
            range(count),
            key=deltas.__getitem__,
        )

        if deltas[axis_index] < self.MOVEMENT_THRESHOLD:
            return

        control = self.learning_control
        if control is None:
            return

        setattr(
            self.mapping,
            control,
            AxisMapping(
                axis_index=axis_index,
                inverted=self.invert_checks[
                    control
                ].isChecked(),
            ),
        )

        self.mapping_labels[control].setText(
            f"Axis {axis_index}"
        )

        self.learning_label.setText(
            f"{DISPLAY_NAMES[control]} learned as Axis {axis_index}."
        )

        self.learning_control = None

    def _load_existing_mapping(self) -> None:
        for control in CONTROL_NAMES:
            item = getattr(
                self.mapping,
                control,
            )

            if item is None:
                self.mapping_labels[control].setText(
                    "Not assigned"
                )
                continue

            self.mapping_labels[control].setText(
                f"Axis {item.axis_index}"
            )
            self.invert_checks[
                control
            ].setChecked(item.inverted)

    def _accept_mapping(self) -> None:
        # Apply current invert checkbox states to all learned mappings.
        for control in CONTROL_NAMES:
            item = getattr(
                self.mapping,
                control,
            )

            if item is not None:
                item.inverted = self.invert_checks[
                    control
                ].isChecked()

        if not self.mapping.complete:
            result = QMessageBox.question(
                self,
                "Incomplete Mapping",
                (
                    "Not all four primary controls have been assigned. "
                    "Save the partial mapping anyway?"
                ),
            )

            if (
                result
                != QMessageBox.StandardButton.Yes
            ):
                return

        self.accept()

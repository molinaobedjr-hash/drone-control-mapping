"""Operator workflow for repeated, interval-labeled mapping trials."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dcmf.core.guided_trials import (
    GUIDED_ACTIONS,
    GuidedTrial,
    GuidedTrialTracker,
)


class GuidedTrialPanel(QWidget):
    """Guide an operator through numbered control-action intervals."""

    trial_started = Signal(str, int)
    trial_ended = Signal(str, int, bool)

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tracker = GuidedTrialTracker()
        self._recording = False

        instructions = QLabel(
            "Choose an action, start the trial, move and hold the "
            "control, click End, then return it to neutral. "
            "Trials cannot overlap."
        )
        instructions.setWordWrap(True)

        self.action_combo = QComboBox()
        self.action_combo.addItems(
            list(GUIDED_ACTIONS)
        )
        self.action_combo.currentTextChanged.connect(
            self._update_progress
        )

        self.repetitions_spin = QSpinBox()
        self.repetitions_spin.setRange(1, 100)
        self.repetitions_spin.setValue(
            self.tracker.target_repetitions
        )
        self.repetitions_spin.valueChanged.connect(
            self._on_target_changed
        )

        form = QFormLayout()
        form.addRow("Action", self.action_combo)
        form.addRow(
            "Target repetitions",
            self.repetitions_spin,
        )

        self.start_button = QPushButton(
            "Start Guided Trial"
        )
        self.end_button = QPushButton(
            "End Guided Trial"
        )
        self.start_button.setEnabled(False)
        self.end_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.end_button)

        self.status_label = QLabel(
            "Start an experiment to begin guided trials."
        )
        self.status_label.setWordWrap(True)
        self.progress_label = QLabel()

        group = QGroupBox("Guided Mapping Trials")
        layout = QVBoxLayout(group)
        layout.addWidget(instructions)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_label)

        outer = QVBoxLayout(self)
        outer.addWidget(group)

        self.start_button.clicked.connect(
            self._begin_trial
        )
        self.end_button.clicked.connect(
            lambda: self.end_active_trial(
                automatic=False
            )
        )
        self._update_progress()

    @property
    def active_trial(self) -> GuidedTrial | None:
        return self.tracker.active_trial

    @property
    def target_repetitions(self) -> int:
        return self.tracker.target_repetitions

    def set_recording(
        self,
        recording: bool,
        *,
        reset: bool = False,
    ) -> None:
        self._recording = recording

        if reset:
            self.tracker.reset(
                self.repetitions_spin.value()
            )
            self.status_label.setText(
                "Ready to start the first guided trial."
            )

        active = self.active_trial is not None
        self.start_button.setEnabled(
            recording and not active
        )
        self.end_button.setEnabled(
            recording and active
        )
        self.action_combo.setEnabled(
            not active
        )
        self.repetitions_spin.setEnabled(
            not recording and not active
        )

        if not recording:
            self.start_button.setEnabled(False)
            self.end_button.setEnabled(False)
            if not active:
                self.status_label.setText(
                    "Start an experiment to begin guided trials."
                )

        self._update_progress()

    def _on_target_changed(
        self,
        value: int,
    ) -> None:
        self.tracker.set_target_repetitions(
            value
        )
        self._update_progress()

    def _begin_trial(self) -> None:
        if not self._recording:
            return

        trial = self.tracker.begin(
            self.action_combo.currentText()
        )
        self.action_combo.setEnabled(False)
        self.repetitions_spin.setEnabled(False)
        self.start_button.setEnabled(False)
        self.end_button.setEnabled(True)
        self.status_label.setText(
            f"ACTIVE: {trial.action} — trial "
            f"{trial.trial_number}. Click End while holding, then release."
        )
        self._update_progress()
        self.trial_started.emit(
            trial.action,
            trial.trial_number,
        )

    def end_active_trial(
        self,
        *,
        automatic: bool,
    ) -> GuidedTrial | None:
        if self.active_trial is None:
            return None

        trial = self.tracker.end()
        self.trial_ended.emit(
            trial.action,
            trial.trial_number,
            automatic,
        )

        self.status_label.setText(
            f"Completed {trial.action} — trial "
            f"{trial.trial_number}."
            + (
                " Automatically ended with the experiment."
                if automatic
                else ""
            )
        )

        if (
            self.tracker.completed[trial.action]
            >= self.tracker.target_repetitions
        ):
            next_action = (
                self.tracker.next_incomplete_action(
                    trial.action
                )
            )
            self.action_combo.setCurrentText(
                next_action
            )

        self.action_combo.setEnabled(True)
        self.repetitions_spin.setEnabled(
            not self._recording
        )
        self.start_button.setEnabled(
            self._recording
        )
        self.end_button.setEnabled(False)
        self._update_progress()
        return trial

    def _update_progress(self) -> None:
        action = self.action_combo.currentText()
        action_count = self.tracker.completed.get(
            action,
            0,
        )
        self.progress_label.setText(
            f"Selected action: {action_count}/"
            f"{self.tracker.target_repetitions} complete | "
            f"Overall: {self.tracker.completed_total}/"
            f"{self.tracker.target_total}"
        )

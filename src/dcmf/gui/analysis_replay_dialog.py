"""Hardware-free synchronized analysis and replay dialog."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dcmf.analysis.session_quality import list_experiments
from dcmf.analysis.synchronized import (
    PRIMARY_CONTROLS,
    analyze_experiment,
    load_session,
)
from dcmf.config.settings import AppSettings
from dcmf.replay.session import ReplaySession


COLORS = {
    "roll": "#4dabf7",
    "pitch": "#69db7c",
    "yaw": "#ff922b",
    "throttle": "#e599f7",
}


class AnalysisReplayDialog(QDialog):
    """Plot, scrub, and replay one recorded experiment."""

    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.session = None
        self.replay: ReplaySession | None = None
        self._feature_dataset_path: Path | None = None
        self._cursor_lines: list[pg.InfiniteLine] = []
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)

        self.setWindowTitle("Synchronized Analysis and Replay")
        self.resize(1250, 850)

        self.experiment_combo = QComboBox()
        self.experiment_combo.setMinimumWidth(420)
        self.load_button = QPushButton("Load Session")
        self.analyze_button = QPushButton("Write Analysis Files")
        self.analyze_button.setEnabled(False)
        self.features_button = QPushButton("Build ML Dataset")
        self.train_button = QPushButton("Train Baseline")
        self.train_button.setEnabled(False)
        selection = QHBoxLayout()
        selection.addWidget(QLabel("Experiment"))
        selection.addWidget(self.experiment_combo, 1)
        selection.addWidget(self.load_button)
        selection.addWidget(self.analyze_button)
        selection.addWidget(self.features_button)
        selection.addWidget(self.train_button)

        self.summary_label = QLabel(
            "Choose a completed experiment. Replay does not require hardware."
        )
        self.summary_label.setWordWrap(True)

        self.input_plot = self._plot("Mapped TX16S input", "normalized")
        self.manual_plot = self._plot(
            "MAVLink MANUAL_CONTROL (TX preferred)", "normalized"
        )
        self.rc_plot = self._plot(
            "Flight-controller RC channels 1–4", "PWM microseconds"
        )
        self.servo_plot = self._plot(
            "Flight-controller SERVO_OUTPUT_RAW 1–8", "PWM microseconds"
        )
        plot_splitter = QSplitter(Qt.Orientation.Vertical)
        plot_splitter.addWidget(self.input_plot)
        plot_splitter.addWidget(self.manual_plot)
        plot_splitter.addWidget(self.rc_plot)
        plot_splitter.addWidget(self.servo_plot)
        plot_splitter.setSizes([210, 210, 210, 210])

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Return to Start")
        self.speed_combo = QComboBox()
        for speed in (0.25, 0.5, 1.0, 2.0, 4.0):
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(2)
        self.time_label = QLabel("0.000 / 0.000 s")
        playback = QHBoxLayout()
        playback.addWidget(self.play_button)
        playback.addWidget(self.stop_button)
        playback.addWidget(QLabel("Speed"))
        playback.addWidget(self.speed_combo)
        playback.addWidget(self.time_label)
        playback.addStretch(1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10_000)
        self.slider.setEnabled(False)
        self.snapshot_label = QLabel("No session loaded")
        self.snapshot_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(selection)
        layout.addWidget(self.summary_label)
        layout.addWidget(plot_splitter, 1)
        layout.addLayout(playback)
        layout.addWidget(self.slider)
        layout.addWidget(self.snapshot_label)

        self.load_button.clicked.connect(self._load_selected)
        self.analyze_button.clicked.connect(self._write_analysis)
        self.features_button.clicked.connect(self._build_features)
        self.train_button.clicked.connect(self._train_model)
        self.play_button.clicked.connect(self._toggle_play)
        self.stop_button.clicked.connect(lambda: self._seek(0.0))
        self.slider.valueChanged.connect(self._slider_changed)
        self._populate_experiments()

    @staticmethod
    def _plot(title: str, units: str) -> pg.PlotWidget:
        widget = pg.PlotWidget(title=title)
        widget.showGrid(x=True, y=True, alpha=0.25)
        widget.setLabel("bottom", "Experiment time", units="s")
        widget.setLabel("left", units)
        widget.addLegend(offset=(10, 10))
        return widget

    def _populate_experiments(self) -> None:
        self.experiment_combo.clear()
        try:
            experiments = list_experiments(self.settings.database_path)
        except Exception as exc:
            self.summary_label.setText(f"Could not read database: {exc}")
            return
        for experiment in experiments:
            started = str(experiment.get("started_utc_iso") or "unknown time")
            if started != "unknown time":
                try:
                    started = datetime.fromisoformat(started).astimezone(
                        timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")
                except ValueError:
                    started = started.replace("T", " ").replace("+00:00", " UTC")
            self.experiment_combo.addItem(
                f"{experiment['name']} — {started}", experiment["id"]
            )
        self.load_button.setEnabled(bool(experiments))

    def _load_selected(self) -> None:
        experiment_id = self.experiment_combo.currentData()
        if not experiment_id:
            return
        try:
            self.session = load_session(
                self.settings.database_path, str(experiment_id)
            )
            self.replay = ReplaySession(self.session)
            self._draw_session()
        except Exception as exc:
            QMessageBox.warning(self, "Analysis", str(exc))
            return
        self.slider.setEnabled(True)
        self.analyze_button.setEnabled(True)
        complete = (
            int(self.session.trials["complete"].fillna(False).sum())
            if "complete" in self.session.trials
            else 0
        )
        self.summary_label.setText(
            f"{self.session.experiment['name']} | "
            f"{len(self.session.controller):,} controller samples | "
            f"{len(self.session.manual_control):,} MANUAL_CONTROL messages | "
            f"{len(self.session.rc_channels):,} RC messages | "
            f"{complete} complete guided trials | host-timestamp alignment"
        )
        self._seek(0.0)

    def _draw_session(self) -> None:
        assert self.session is not None
        for plot in (
            self.input_plot, self.manual_plot, self.rc_plot, self.servo_plot
        ):
            plot.clear()
            plot.addLegend(offset=(10, 10))
        self._draw_controls(self.input_plot, self.session.controller)
        manual = self.session.manual_control
        if not manual.empty and (manual["direction"] == "TX").any():
            manual = manual[manual["direction"] == "TX"]
        self._draw_controls(self.manual_plot, manual)
        rc = self.session.rc_channels
        for index, control in enumerate(PRIMARY_CONTROLS, start=1):
            channel = {"roll": 1, "pitch": 2, "throttle": 3, "yaw": 4}[control]
            self._draw_line(
                self.rc_plot,
                rc,
                f"ch{channel}",
                f"CH{channel} {control}",
                COLORS[control],
            )
        servo_colors = (
            "#4dabf7", "#69db7c", "#ff922b", "#e599f7",
            "#ffd43b", "#63e6be", "#ff6b6b", "#748ffc",
        )
        for index, color in enumerate(servo_colors, start=1):
            self._draw_line(
                self.servo_plot,
                self.session.servo_outputs,
                f"servo{index}",
                f"Servo {index}",
                color,
            )
        self._cursor_lines = []
        for plot in (
            self.input_plot, self.manual_plot, self.rc_plot, self.servo_plot
        ):
            cursor = pg.InfiniteLine(pos=0.0, angle=90, pen=pg.mkPen("#ffffff", width=2))
            plot.addItem(cursor)
            self._cursor_lines.append(cursor)
            for trial in self.session.trials.to_dict(orient="records"):
                if not trial.get("complete"):
                    continue
                for time_key in ("start_time_s", "end_time_s"):
                    marker = pg.InfiniteLine(
                        pos=float(trial[time_key]),
                        angle=90,
                        pen=pg.mkPen("#868e96", width=1, style=Qt.PenStyle.DotLine),
                    )
                    plot.addItem(marker)

    def _draw_controls(self, plot: pg.PlotWidget, frame) -> None:
        for control in PRIMARY_CONTROLS:
            self._draw_line(plot, frame, control, control, COLORS[control])

    @staticmethod
    def _draw_line(plot, frame, column: str, label: str, color: str) -> None:
        if frame.empty or column not in frame:
            return
        clean = frame[["time_s", column]].dropna()
        if clean.empty:
            return
        step = max(1, len(clean) // 25_000)
        clean = clean.iloc[::step]
        plot.plot(
            clean["time_s"].to_numpy(dtype=float),
            clean[column].to_numpy(dtype=float),
            name=label,
            pen=pg.mkPen(color, width=1.5),
        )

    def _toggle_play(self) -> None:
        if self.replay is None:
            return
        if self._timer.isActive():
            self._timer.stop()
            self.play_button.setText("Play")
        else:
            if self.replay.cursor_s >= self.replay.duration_s:
                self._seek(0.0)
            self._timer.start()
            self.play_button.setText("Pause")

    def _advance(self) -> None:
        assert self.replay is not None
        speed = float(self.speed_combo.currentData())
        snapshot = self.replay.advance(self._timer.interval() / 1000.0, speed)
        self._show_snapshot(snapshot)
        self._sync_slider()
        if self.replay.cursor_s >= self.replay.duration_s:
            self._timer.stop()
            self.play_button.setText("Play")

    def _slider_changed(self, value: int) -> None:
        if self.replay is None or self.replay.duration_s <= 0:
            return
        self._seek(value / 10_000.0 * self.replay.duration_s, update_slider=False)

    def _seek(self, time_s: float, *, update_slider: bool = True) -> None:
        if self.replay is None:
            return
        snapshot = self.replay.seek(time_s)
        self._show_snapshot(snapshot)
        if update_slider:
            self._sync_slider()

    def _sync_slider(self) -> None:
        assert self.replay is not None
        fraction = (
            self.replay.cursor_s / self.replay.duration_s
            if self.replay.duration_s > 0
            else 0.0
        )
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(fraction * 10_000)))
        self.slider.blockSignals(False)

    def _show_snapshot(self, snapshot) -> None:
        assert self.replay is not None
        for cursor in self._cursor_lines:
            cursor.setValue(snapshot.time_s)
        self.time_label.setText(
            f"{snapshot.time_s:.3f} / {self.replay.duration_s:.3f} s"
        )
        trial = snapshot.active_trial
        trial_text = (
            f"{trial['action']} trial {trial['trial_number']}"
            if trial
            else "no active guided interval"
        )
        controls = snapshot.controller
        values = " ".join(
            f"{name}={controls.get(name):+.3f}"
            if isinstance(controls.get(name), (int, float, np.number))
            else f"{name}=—"
            for name in PRIMARY_CONTROLS
        )
        self.snapshot_label.setText(f"{trial_text} | TX16S {values}")

    def _write_analysis(self) -> None:
        if self.session is None:
            return
        try:
            result = analyze_experiment(
                self.settings.database_path,
                self.session.experiment_id,
                self.settings.analysis_directory,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Analysis", str(exc))
            return
        QMessageBox.information(
            self,
            "Analysis Complete",
            f"Wrote {result.row_count:,} synchronized rows to:\n{result.output_directory}",
        )

    def _build_features(self) -> None:
        from dcmf.ml.features import generate_feature_dataset

        tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = self.settings.analysis_directory / "ml" / tag
        try:
            result = generate_feature_dataset(
                self.settings.database_path,
                output,
                include_iq_power=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "ML Dataset", str(exc))
            return
        self._feature_dataset_path = result.csv_path
        self.train_button.setEnabled(result.row_count > 0)
        QMessageBox.information(
            self,
            "ML Dataset Complete",
            f"Wrote {result.row_count} trial rows and {result.feature_count} features to:\n"
            f"{result.csv_path}",
        )

    def _train_model(self) -> None:
        from dcmf.ml.classifier import train_random_forest

        if self._feature_dataset_path is None:
            return
        output = self._feature_dataset_path.parent / "random_forest"
        try:
            result = train_random_forest(self._feature_dataset_path, output)
        except Exception as exc:
            QMessageBox.warning(self, "Random Forest", str(exc))
            return
        if result.status != "complete":
            QMessageBox.information(
                self,
                "More Data Required",
                f"The evaluation is not yet statistically valid. See:\n{result.metrics_path}",
            )
            return
        QMessageBox.information(
            self,
            "Training Complete",
            f"Model and evaluation artifacts were written to:\n{result.output_directory}",
        )

    def closeEvent(self, event) -> None:
        self._timer.stop()
        event.accept()

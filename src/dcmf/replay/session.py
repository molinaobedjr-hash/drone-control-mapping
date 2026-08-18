"""Deterministic, hardware-free replay state for recorded DCMF sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from dcmf.analysis.synchronized import SessionData


@dataclass(slots=True, frozen=True)
class ReplaySnapshot:
    """Values nearest the current replay cursor."""

    time_s: float
    controller: dict[str, Any]
    manual_control: dict[str, Any]
    rc_channels: dict[str, Any]
    servo_outputs: dict[str, Any]
    active_trial: dict[str, Any] | None


class ReplaySession:
    """Cursor and nearest-sample lookup independent of Qt."""

    def __init__(self, data: SessionData) -> None:
        self.data = data
        self.cursor_s = 0.0
        start = int(data.experiment["started_monotonic_ns"])
        ended = data.experiment.get("ended_monotonic_ns")
        if ended is not None:
            self.duration_s = max(0.0, (int(ended) - start) / 1_000_000_000.0)
        else:
            candidates = []
            for frame in (
                data.controller,
                data.manual_control,
                data.rc_channels,
                data.servo_outputs,
                data.events,
                data.sdr,
            ):
                if not frame.empty and "time_s" in frame:
                    candidates.append(float(frame["time_s"].max()))
            self.duration_s = max(candidates, default=0.0)

    def seek(self, time_s: float) -> ReplaySnapshot:
        self.cursor_s = max(0.0, min(self.duration_s, float(time_s)))
        return self.snapshot()

    def advance(self, elapsed_s: float, speed: float = 1.0) -> ReplaySnapshot:
        return self.seek(self.cursor_s + max(0.0, elapsed_s) * max(0.0, speed))

    def snapshot(self) -> ReplaySnapshot:
        return ReplaySnapshot(
            time_s=self.cursor_s,
            controller=self._nearest(self.data.controller),
            manual_control=self._nearest(self.data.manual_control),
            rc_channels=self._nearest(self.data.rc_channels),
            servo_outputs=self._nearest(self.data.servo_outputs),
            active_trial=self._active_trial(),
        )

    def events_between(self, start_s: float, end_s: float) -> list[dict[str, Any]]:
        if self.data.events.empty:
            return []
        low, high = sorted((float(start_s), float(end_s)))
        rows = self.data.events[
            (self.data.events["time_s"] > low)
            & (self.data.events["time_s"] <= high)
        ]
        return rows.to_dict(orient="records")

    def _nearest(self, frame: pd.DataFrame) -> dict[str, Any]:
        if frame.empty or "time_s" not in frame:
            return {}
        distances = (frame["time_s"] - self.cursor_s).abs()
        if distances.empty:
            return {}
        row = frame.loc[distances.idxmin()]
        return {
            key: (None if pd.isna(value) else value)
            for key, value in row.to_dict().items()
        }

    def _active_trial(self) -> dict[str, Any] | None:
        trials = self.data.trials
        if trials.empty:
            return None
        active = trials[
            trials.get("complete", False).fillna(False)
            & (trials["start_time_s"] <= self.cursor_s)
            & (trials["end_time_s"] >= self.cursor_s)
        ]
        if active.empty:
            return None
        row = active.iloc[0]
        return {
            key: (None if pd.isna(value) else value)
            for key, value in row.to_dict().items()
        }

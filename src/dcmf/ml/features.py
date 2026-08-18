"""Guided-trial feature extraction for DCMF control mapping."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from dcmf.analysis.session_quality import list_experiments
from dcmf.analysis.synchronized import PRIMARY_CONTROLS, SessionData, load_session


@dataclass(slots=True, frozen=True)
class FeatureDatasetResult:
    """Files and dimensions produced by feature extraction."""

    csv_path: Path
    metadata_path: Path
    row_count: int
    feature_count: int
    experiment_count: int


def _numeric_stats(
    row: dict[str, Any],
    frame: pd.DataFrame,
    *,
    prefix: str,
    columns: Iterable[str],
) -> None:
    for column in columns:
        values = pd.to_numeric(frame.get(column), errors="coerce").dropna()
        stem = f"{prefix}_{column}"
        if values.empty:
            for suffix in (
                "mean", "std", "min", "max", "range", "abs_mean",
                "peak_abs", "delta",
            ):
                row[f"{stem}_{suffix}"] = np.nan
            continue
        row[f"{stem}_mean"] = float(values.mean())
        row[f"{stem}_std"] = float(values.std(ddof=0))
        row[f"{stem}_min"] = float(values.min())
        row[f"{stem}_max"] = float(values.max())
        row[f"{stem}_range"] = float(values.max() - values.min())
        row[f"{stem}_abs_mean"] = float(values.abs().mean())
        row[f"{stem}_peak_abs"] = float(values.abs().max())
        row[f"{stem}_delta"] = float(values.iloc[-1] - values.iloc[0])


def _slice(frame: pd.DataFrame, start_ns: int, end_ns: int) -> pd.DataFrame:
    if frame.empty or "monotonic_ns" not in frame:
        return frame.iloc[0:0]
    return frame[
        (frame["monotonic_ns"] >= start_ns)
        & (frame["monotonic_ns"] <= end_ns)
    ]


def _resolve_iq_path(path: str, repository_root: Path) -> Path | None:
    if not path:
        return None
    raw = Path(path)
    candidates = [raw] if raw.is_absolute() else [repository_root / raw, raw]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _iq_window_power(
    session: SessionData,
    start_ns: int,
    end_ns: int,
    repository_root: Path,
    *,
    max_complex_samples: int = 250_000,
) -> dict[str, Any]:
    """Estimate sc16 power for a host-timestamp trial window.

    The CAPTURE_START event time is used as sample zero. Process startup and
    buffering make this an approximation, which is explicitly recorded in the
    returned fields.
    """
    starts = session.sdr[session.sdr.get("record_kind") == "CAPTURE_START"]
    if starts.empty:
        return {
            "sdr_power_dbfs": np.nan,
            "sdr_peak_dbfs": np.nan,
            "sdr_iq_samples_used": 0,
            "sdr_iq_available": False,
        }
    capture = starts[starts["monotonic_ns"] <= start_ns]
    if capture.empty:
        capture = starts.iloc[[0]]
    item = capture.iloc[-1]
    sample_rate = pd.to_numeric(item.get("sample_rate_hz"), errors="coerce")
    path = _resolve_iq_path(str(item.get("iq_file") or ""), repository_root)
    if path is None or pd.isna(sample_rate) or float(sample_rate) <= 0:
        return {
            "sdr_power_dbfs": np.nan,
            "sdr_peak_dbfs": np.nan,
            "sdr_iq_samples_used": 0,
            "sdr_iq_available": False,
        }

    capture_start_ns = int(item["monotonic_ns"])
    start_sample = max(
        0,
        int((start_ns - capture_start_ns) / 1_000_000_000.0 * float(sample_rate)),
    )
    interval_samples = max(
        0,
        int((end_ns - start_ns) / 1_000_000_000.0 * float(sample_rate)),
    )
    requested = min(interval_samples, max_complex_samples)
    if requested < 1:
        return {
            "sdr_power_dbfs": np.nan,
            "sdr_peak_dbfs": np.nan,
            "sdr_iq_samples_used": 0,
            "sdr_iq_available": True,
        }

    with path.open("rb") as handle:
        handle.seek(start_sample * 4)
        raw = np.fromfile(handle, dtype="<i2", count=requested * 2)
    if len(raw) < 2:
        return {
            "sdr_power_dbfs": np.nan,
            "sdr_peak_dbfs": np.nan,
            "sdr_iq_samples_used": 0,
            "sdr_iq_available": True,
        }
    raw = raw[: len(raw) - len(raw) % 2].astype(np.float32) / 32768.0
    complex_power = raw[0::2] ** 2 + raw[1::2] ** 2
    mean_power = float(np.mean(complex_power))
    peak_power = float(np.max(complex_power))
    tiny = np.finfo(np.float32).tiny
    return {
        "sdr_power_dbfs": float(10.0 * math.log10(max(mean_power, tiny))),
        "sdr_peak_dbfs": float(10.0 * math.log10(max(peak_power, tiny))),
        "sdr_iq_samples_used": int(len(complex_power)),
        "sdr_iq_available": True,
    }


def extract_trial_features(
    session: SessionData,
    *,
    repository_root: Path = Path("."),
    include_iq_power: bool = True,
) -> pd.DataFrame:
    """Return one labeled feature row per complete guided trial."""
    records: list[dict[str, Any]] = []
    for trial in session.trials.to_dict(orient="records"):
        if not trial.get("complete"):
            continue
        start_ns = int(trial["start_monotonic_ns"])
        end_ns = int(trial["end_monotonic_ns"])
        controller = _slice(session.controller, start_ns, end_ns)
        manual = _slice(session.manual_control, start_ns, end_ns)
        if not manual.empty and (manual["direction"] == "TX").any():
            manual = manual[manual["direction"] == "TX"]
        rc = _slice(session.rc_channels, start_ns, end_ns)
        if not rc.empty and (rc["direction"] == "RX").any():
            rc = rc[rc["direction"] == "RX"]
        servos = _slice(session.servo_outputs, start_ns, end_ns)
        if not servos.empty and (servos["direction"] == "RX").any():
            servos = servos[servos["direction"] == "RX"]

        row: dict[str, Any] = {
            "experiment_id": session.experiment_id,
            "experiment_name": str(session.experiment.get("name") or ""),
            "action": str(trial["action"]),
            "trial_number": int(trial["trial_number"]),
            "start_monotonic_ns": start_ns,
            "end_monotonic_ns": end_ns,
            "duration_s": float(trial["duration_s"]),
            "automatic_end": bool(trial.get("automatic_end", False)),
            "controller_sample_count": int(len(controller)),
            "manual_control_count": int(len(manual)),
            "rc_channel_count": int(len(rc)),
            "servo_output_count": int(len(servos)),
            "controller_rate_hz": (
                float(len(controller) / row_duration)
                if (row_duration := float(trial["duration_s"])) > 0
                else np.nan
            ),
            "manual_control_rate_hz": (
                float(len(manual) / row_duration) if row_duration > 0 else np.nan
            ),
            "rc_channel_rate_hz": (
                float(len(rc) / row_duration) if row_duration > 0 else np.nan
            ),
            "servo_output_rate_hz": (
                float(len(servos) / row_duration) if row_duration > 0 else np.nan
            ),
        }
        _numeric_stats(
            row, controller, prefix="input", columns=PRIMARY_CONTROLS
        )
        _numeric_stats(
            row, manual, prefix="manual", columns=PRIMARY_CONTROLS
        )
        _numeric_stats(
            row, rc, prefix="rc", columns=("ch1", "ch2", "ch3", "ch4", *PRIMARY_CONTROLS)
        )
        _numeric_stats(
            row,
            servos,
            prefix="servo",
            columns=tuple(f"servo{index}" for index in range(1, 17)),
        )
        if include_iq_power:
            row.update(
                _iq_window_power(
                    session, start_ns, end_ns, Path(repository_root)
                )
            )
        else:
            row.update(
                {
                    "sdr_power_dbfs": np.nan,
                    "sdr_peak_dbfs": np.nan,
                    "sdr_iq_samples_used": 0,
                    "sdr_iq_available": False,
                }
            )
        records.append(row)
    return pd.DataFrame.from_records(records)


def generate_feature_dataset(
    database_path: Path,
    output_directory: Path,
    *,
    experiment_ids: Iterable[str] | None = None,
    include_iq_power: bool = True,
) -> FeatureDatasetResult:
    """Build a multi-session labeled CSV plus provenance metadata."""
    database_path = Path(database_path)
    if experiment_ids is None:
        experiment_ids = [
            str(item["id"])
            for item in list_experiments(database_path, completed_only=True)
        ]
    ids = list(dict.fromkeys(str(value) for value in experiment_ids))
    repository_root = database_path.resolve().parent.parent
    frames = []
    errors: dict[str, str] = {}
    for experiment_id in ids:
        try:
            session = load_session(database_path, experiment_id)
            frames.append(
                extract_trial_features(
                    session,
                    repository_root=repository_root,
                    include_iq_power=include_iq_power,
                )
            )
        except Exception as exc:
            errors[experiment_id] = str(exc)
    dataset = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame()
    )
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / "guided_trial_features.csv"
    metadata_path = output_directory / "feature_metadata.json"
    dataset.to_csv(csv_path, index=False)
    excluded = {
        "experiment_id", "experiment_name", "action", "trial_number",
        "start_monotonic_ns", "end_monotonic_ns", "automatic_end",
    }
    feature_columns = [
        column
        for column in dataset.columns
        if column not in excluded and pd.api.types.is_numeric_dtype(dataset[column])
    ]
    metadata = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "database_path": str(database_path),
        "experiment_ids_requested": ids,
        "experiment_errors": errors,
        "row_count": int(len(dataset)),
        "feature_count": len(feature_columns),
        "feature_columns": feature_columns,
        "label_column": "action",
        "group_column": "experiment_id",
        "unit_of_observation": "one complete guided trial interval",
        "iq_power_enabled": include_iq_power,
        "synchronization": {
            "method": "shared host monotonic/software event timestamps",
            "hardware_synchronized": False,
            "iq_window_alignment": "approximate CAPTURE_START event offset",
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return FeatureDatasetResult(
        csv_path=csv_path,
        metadata_path=metadata_path,
        row_count=len(dataset),
        feature_count=len(feature_columns),
        experiment_count=len(set(dataset.get("experiment_id", []))),
    )

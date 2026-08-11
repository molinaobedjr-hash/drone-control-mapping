"""Create and finalize persistent per-experiment packages."""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dcmf.utils.timestamps import Timestamp


@dataclass(slots=True, frozen=True)
class ExperimentPackage:
    """Filesystem locations associated with one experiment."""

    experiment_id: str
    folder_name: str
    package_directory: Path
    export_directory: Path
    iq_source_directory: Path


def _safe_name(value: str) -> str:
    """Return a short filesystem-safe experiment name."""
    cleaned = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        value.strip(),
    ).strip("-_")
    return cleaned[:80] or "experiment"


def _utc_iso(utc_ns: int | None) -> str | None:
    if utc_ns is None:
        return None
    return datetime.fromtimestamp(
        utc_ns / 1_000_000_000,
        tz=timezone.utc,
    ).isoformat()


def _write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Atomically write readable JSON."""
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _create_iq_reference(
    package_directory: Path,
    iq_source_directory: Path,
) -> None:
    """Expose the existing IQ directory without duplicating large files."""
    iq_reference = package_directory / "iq"
    relative_target = os.path.relpath(
        iq_source_directory.resolve(),
        start=package_directory.resolve(),
    )

    try:
        iq_reference.symlink_to(
            relative_target,
            target_is_directory=True,
        )
    except OSError:
        # Some filesystems do not allow symlinks. Retain an explicit,
        # machine-readable association instead of copying raw IQ data.
        iq_reference.mkdir(
            parents=True,
            exist_ok=True,
        )
        _write_json(
            iq_reference / "source.json",
            {
                "iq_source_directory": str(
                    iq_source_directory
                ),
            },
        )


def create_experiment_package(
    *,
    experiment_root: Path,
    export_root: Path,
    iq_root: Path,
    experiment_id: str,
    metadata: dict[str, Any],
    timestamp: Timestamp,
    application_name: str,
    application_version: str,
    database_path: Path,
    controller_mapping: dict[str, Any],
    mavlink_configuration: dict[str, Any],
    sdr_configuration: dict[str, Any],
    guided_trial_configuration: (
        dict[str, Any] | None
    ) = None,
) -> ExperimentPackage:
    """Create the initial files and IQ association for an experiment."""
    started = datetime.fromtimestamp(
        timestamp.utc_ns / 1_000_000_000,
        tz=timezone.utc,
    )
    base_name = (
        f"{started.strftime('%Y-%m-%d_%H%M%S')}_"
        f"{_safe_name(str(metadata.get('name') or 'experiment'))}"
    )

    experiment_root = Path(experiment_root)
    export_root = Path(export_root)
    package_directory = experiment_root / base_name
    export_directory = export_root / base_name

    if package_directory.exists() or export_directory.exists():
        base_name = f"{base_name}_{experiment_id[:8]}"
        package_directory = experiment_root / base_name
        export_directory = export_root / base_name

    package_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    iq_source_directory = (
        Path(iq_root) / experiment_id
    )
    iq_source_directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    _create_iq_reference(
        package_directory,
        iq_source_directory,
    )

    package = ExperimentPackage(
        experiment_id=experiment_id,
        folder_name=base_name,
        package_directory=package_directory,
        export_directory=export_directory,
        iq_source_directory=iq_source_directory,
    )

    experiment_metadata = {
        "experiment_id": experiment_id,
        "name": str(
            metadata.get("name")
            or "Untitled Experiment"
        ),
        "operator": str(
            metadata.get("operator") or ""
        ),
        "notes": str(
            metadata.get("notes") or ""
        ),
        "started_monotonic_ns": timestamp.monotonic_ns,
        "started_utc_ns": timestamp.utc_ns,
        "started_utc_iso": _utc_iso(timestamp.utc_ns),
        "ended_monotonic_ns": None,
        "ended_utc_ns": None,
        "ended_utc_iso": None,
        "status": "recording",
    }
    _write_json(
        package_directory / "metadata.json",
        experiment_metadata,
    )

    session_info = {
        "application": {
            "name": application_name,
            "version": application_version,
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "storage": {
            "database_path": str(database_path),
            "experiment_directory": str(
                package_directory
            ),
            "export_directory": str(
                export_directory
            ),
            "iq_source_directory": str(
                iq_source_directory
            ),
        },
        "synchronization": {
            "method": "shared host monotonic/software event timestamps",
            "monotonic_clock": "time.perf_counter_ns",
            "wall_clock": "time.time_ns",
            "hardware_synchronized": False,
        },
        "controller_mapping": controller_mapping,
        "mavlink": mavlink_configuration,
        "sdr": sdr_configuration,
        "guided_trials": (
            guided_trial_configuration or {}
        ),
    }
    _write_json(
        package_directory / "session_info.json",
        session_info,
    )

    notes = experiment_metadata["notes"]
    (package_directory / "notes.txt").write_text(
        notes + ("\n" if notes else ""),
        encoding="utf-8",
    )

    return package


def finalize_experiment_package(
    package: ExperimentPackage,
    experiment: dict[str, Any],
    iq_files: list[str],
) -> None:
    """Update package metadata after SQLite marks an experiment complete."""
    metadata_path = (
        package.package_directory
        / "metadata.json"
    )
    current: dict[str, Any] = {}

    if metadata_path.exists():
        try:
            current = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            current = {}

    current.update(experiment)
    current["started_utc_iso"] = _utc_iso(
        experiment.get("started_utc_ns")
    )
    current["ended_utc_iso"] = _utc_iso(
        experiment.get("ended_utc_ns")
    )
    current["iq_files"] = iq_files
    current["export_directory"] = str(
        package.export_directory
    )

    _write_json(
        metadata_path,
        current,
    )

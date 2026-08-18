"""Read-only data-quality checks for completed DCMF sessions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dcmf.core.guided_trials import GUIDED_ACTIONS


PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"

REQUIRED_PACKAGE_FILES = (
    "metadata.json",
    "session_info.json",
    "notes.txt",
    "iq",
)
REQUIRED_EXPORT_FILES = (
    "controller_samples.csv",
    "mavlink_messages.csv",
    "events.csv",
    "sdr_records.csv",
    "experiment_summary.json",
)


@dataclass(slots=True, frozen=True)
class QualityCheck:
    """One human-readable session validation result."""

    key: str
    title: str
    status: str
    message: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(slots=True, frozen=True)
class SessionQualityReport:
    """Combined database, package, export, and trial review."""

    experiment: dict[str, Any]
    counts: dict[str, int]
    guided_trials: dict[str, Any]
    iq_files: tuple[dict[str, Any], ...]
    package_directory: str | None
    export_directory: str | None
    checks: tuple[QualityCheck, ...]
    generated_utc: str

    @property
    def overall_status(self) -> str:
        statuses = {
            check.status
            for check in self.checks
        }
        if FAIL in statuses:
            return FAIL
        if WARNING in statuses:
            return WARNING
        return PASS

    @property
    def status_counts(self) -> dict[str, int]:
        return {
            status: sum(
                check.status == status
                for check in self.checks
            )
            for status in (
                PASS,
                WARNING,
                FAIL,
            )
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "overall_status": self.overall_status,
            "status_counts": self.status_counts,
            "counts": self.counts,
            "guided_trials": self.guided_trials,
            "iq_files": list(self.iq_files),
            "package_directory": self.package_directory,
            "export_directory": self.export_directory,
            "checks": [
                asdict(check)
                for check in self.checks
            ],
            "generated_utc": self.generated_utc,
        }


def _utc_iso(
    utc_ns: int | None,
) -> str | None:
    if utc_ns is None:
        return None
    return datetime.fromtimestamp(
        utc_ns / 1_000_000_000,
        tz=timezone.utc,
    ).isoformat()


def _connect_read_only(
    database_path: Path,
) -> sqlite3.Connection:
    resolved = Path(database_path).resolve()
    connection = sqlite3.connect(
        f"file:{resolved}?mode=ro",
        uri=True,
        timeout=10.0,
    )
    connection.row_factory = sqlite3.Row
    return connection


def list_experiments(
    database_path: Path,
    *,
    completed_only: bool = True,
) -> list[dict[str, Any]]:
    """Return newest-first experiment metadata for the review selector."""
    connection = _connect_read_only(
        database_path
    )
    try:
        where = (
            "WHERE status = 'complete'"
            if completed_only
            else ""
        )
        rows = connection.execute(
            f"""
            SELECT *
            FROM experiments
            {where}
            ORDER BY started_utc_ns DESC
            """
        ).fetchall()
        experiments = []
        for row in rows:
            item = dict(row)
            item["started_utc_iso"] = _utc_iso(
                item.get("started_utc_ns")
            )
            item["ended_utc_iso"] = _utc_iso(
                item.get("ended_utc_ns")
            )
            experiments.append(item)
        return experiments
    finally:
        connection.close()


def _read_json(
    path: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, str(exc)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"

    if not isinstance(payload, dict):
        return None, "JSON root is not an object"
    return payload, None


def _matching_directory(
    root: Path,
    experiment_id: str,
    metadata_name: str,
) -> Path | None:
    root = Path(root)
    if not root.is_dir():
        return None

    for candidate in sorted(
        root.iterdir(),
        reverse=True,
    ):
        if not candidate.is_dir():
            continue
        metadata, error = _read_json(
            candidate / metadata_name
        )
        if error or metadata is None:
            continue

        nested_experiment = metadata.get(
            "experiment"
        )
        nested_id = (
            nested_experiment.get("id")
            if isinstance(
                nested_experiment,
                dict,
            )
            else None
        )
        recorded_id = (
            metadata.get("id")
            or metadata.get("experiment_id")
            or nested_id
        )
        if recorded_id == experiment_id:
            return candidate

    return None


def _guided_trial_quality(
    rows: list[sqlite3.Row],
) -> dict[str, Any]:
    pairs: dict[
        tuple[str, int],
        dict[str, list[dict[str, Any]]],
    ] = {}
    observed_targets: set[int] = set()
    invalid_event_count = 0
    automatic_end_count = 0
    started_event_count = 0
    ended_event_count = 0

    for row in rows:
        kind = str(row["kind"])
        slot = (
            "start"
            if kind == "ACTION_START"
            else "end"
        )
        if slot == "start":
            started_event_count += 1
        else:
            ended_event_count += 1

        try:
            payload = json.loads(
                row["payload_json"] or "{}"
            )
        except (TypeError, json.JSONDecodeError):
            invalid_event_count += 1
            continue
        if not isinstance(payload, dict):
            invalid_event_count += 1
            continue

        action = str(
            payload.get("action") or ""
        ).strip()
        try:
            trial_number = int(
                payload.get(
                    "trial_number",
                    payload.get("trial"),
                )
            )
        except (TypeError, ValueError):
            invalid_event_count += 1
            continue

        if not action or trial_number < 1:
            invalid_event_count += 1
            continue

        try:
            target = int(
                payload.get(
                    "target_repetitions"
                )
            )
        except (TypeError, ValueError):
            target = 0
        if target > 0:
            observed_targets.add(target)

        automatic = bool(
            payload.get("automatic", False)
        )
        if slot == "end" and automatic:
            automatic_end_count += 1

        pair = pairs.setdefault(
            (action, trial_number),
            {
                "start": [],
                "end": [],
            },
        )
        pair[slot].append(
            {
                "monotonic_ns": int(
                    row["monotonic_ns"]
                ),
                "label": payload.get(
                    "label",
                    f"{action}_{slot.upper()}",
                ),
                "automatic": automatic,
            }
        )

    duplicate_event_count = 0
    incomplete_trial_count = 0
    invalid_duration_count = 0
    complete_trial_count = 0
    completed_by_action = {
        action: 0
        for action in GUIDED_ACTIONS
    }
    trials: list[dict[str, Any]] = []

    action_order = {
        action: index
        for index, action in enumerate(
            GUIDED_ACTIONS
        )
    }
    for (
        action,
        trial_number,
    ), pair in sorted(
        pairs.items(),
        key=lambda item: (
            action_order.get(
                item[0][0],
                len(action_order),
            ),
            item[0][0],
            item[0][1],
        ),
    ):
        starts = pair["start"]
        ends = pair["end"]
        duplicate_event_count += max(
            0,
            len(starts) - 1,
        ) + max(
            0,
            len(ends) - 1,
        )

        if not starts:
            status = "missing_start"
            incomplete_trial_count += 1
        elif not ends:
            status = "missing_end"
            incomplete_trial_count += 1
        elif (
            ends[0]["monotonic_ns"]
            < starts[0]["monotonic_ns"]
        ):
            status = "invalid_duration"
            invalid_duration_count += 1
        else:
            status = "complete"
            complete_trial_count += 1
            completed_by_action.setdefault(
                action,
                0,
            )
            completed_by_action[action] += 1

        trials.append(
            {
                "action": action,
                "trial_number": trial_number,
                "status": status,
                "start_count": len(starts),
                "end_count": len(ends),
            }
        )

    targets = sorted(observed_targets)
    return {
        "started_event_count": started_event_count,
        "ended_event_count": ended_event_count,
        "complete_trial_count": complete_trial_count,
        "incomplete_trial_count": incomplete_trial_count,
        "automatic_end_count": automatic_end_count,
        "invalid_event_count": invalid_event_count,
        "duplicate_event_count": duplicate_event_count,
        "invalid_duration_count": invalid_duration_count,
        "observed_target_repetitions": targets,
        "target_repetitions": (
            targets[0]
            if len(targets) == 1
            else None
        ),
        "completed_by_action": completed_by_action,
        "trials": trials,
    }


def _resolve_iq_file(
    raw_path: str,
    *,
    database_path: Path,
    iq_root: Path,
    experiment_id: str,
    package_directory: Path | None,
) -> Path:
    stored = Path(raw_path)
    if stored.is_absolute():
        return stored

    candidates = [
        Path(database_path).resolve().parent.parent
        / stored,
        Path(iq_root)
        / experiment_id
        / stored.name,
    ]
    if package_directory is not None:
        candidates.append(
            package_directory
            / "iq"
            / stored.name
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def evaluate_session(
    *,
    database_path: Path,
    experiment_root: Path,
    export_root: Path,
    iq_root: Path,
    experiment_id: str,
) -> SessionQualityReport:
    """Evaluate one session without modifying SQLite or its files."""
    database_path = Path(database_path)
    package_directory = _matching_directory(
        experiment_root,
        experiment_id,
        "metadata.json",
    )
    export_directory = None
    if package_directory is not None:
        matching_export = (
            Path(export_root)
            / package_directory.name
        )
        if matching_export.is_dir():
            export_directory = matching_export
    if export_directory is None:
        export_directory = _matching_directory(
            export_root,
            experiment_id,
            "experiment_summary.json",
        )

    connection = _connect_read_only(
        database_path
    )
    try:
        row = connection.execute(
            """
            SELECT *
            FROM experiments
            WHERE id = ?
            """,
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                "Experiment was not found in SQLite: "
                f"{experiment_id}"
            )
        experiment = dict(row)
        experiment["started_utc_iso"] = _utc_iso(
            experiment.get("started_utc_ns")
        )
        experiment["ended_utc_iso"] = _utc_iso(
            experiment.get("ended_utc_ns")
        )

        count_row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM controller_samples
                 WHERE experiment_id = ?) AS controller_samples,
                (SELECT COUNT(*) FROM mavlink_messages
                 WHERE experiment_id = ?) AS mavlink_messages,
                (SELECT COUNT(*) FROM mavlink_messages
                 WHERE experiment_id = ?
                   AND message_name = 'HEARTBEAT') AS heartbeats,
                (SELECT COUNT(*) FROM mavlink_messages
                 WHERE experiment_id = ?
                   AND direction = 'TX'
                   AND message_name = 'MANUAL_CONTROL') AS manual_control_tx,
                (SELECT COUNT(*) FROM mavlink_messages
                 WHERE experiment_id = ?
                   AND direction = 'RX'
                   AND message_name IN ('RC_CHANNELS', 'RC_CHANNELS_RAW'))
                   AS rc_channel_rx,
                (SELECT COUNT(*) FROM mavlink_messages
                 WHERE experiment_id = ?
                   AND direction = 'RX'
                   AND message_name = 'SERVO_OUTPUT_RAW') AS servo_output_rx,
                (SELECT COUNT(*) FROM mavlink_messages
                 WHERE experiment_id = ?
                   AND (raw_hex IS NULL OR trim(raw_hex) = ''))
                   AS missing_raw_hex,
                (SELECT COUNT(*) FROM sdr_records
                 WHERE experiment_id = ?) AS sdr_records,
                (SELECT COUNT(*) FROM events
                 WHERE experiment_id = ?) AS events,
                (SELECT COUNT(*) FROM events
                 WHERE experiment_id = ?
                   AND source = 'OPERATOR'
                   AND kind = 'MARKER') AS manual_markers
            """,
            (experiment_id,) * 10,
        ).fetchone()
        counts = {
            key: int(count_row[key])
            for key in count_row.keys()
        }

        guided_rows = connection.execute(
            """
            SELECT
                monotonic_ns,
                kind,
                payload_json
            FROM events
            WHERE experiment_id = ?
              AND source = 'OPERATOR'
              AND kind IN ('ACTION_START', 'ACTION_END')
            ORDER BY monotonic_ns, id
            """,
            (experiment_id,),
        ).fetchall()
        guided_trials = _guided_trial_quality(
            list(guided_rows)
        )

        sdr_rows = connection.execute(
            """
            SELECT
                record_kind,
                iq_file,
                metadata_json
            FROM sdr_records
            WHERE experiment_id = ?
            ORDER BY monotonic_ns, id
            """,
            (experiment_id,),
        ).fetchall()

        out_of_bounds = 0
        start_ns = experiment[
            "started_monotonic_ns"
        ]
        end_ns = experiment.get(
            "ended_monotonic_ns"
        )
        if end_ns is not None:
            for table in (
                "events",
                "controller_samples",
                "mavlink_messages",
                "sdr_records",
            ):
                out_of_bounds += int(
                    connection.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {table}
                        WHERE experiment_id = ?
                          AND (
                              monotonic_ns < ?
                              OR monotonic_ns > ?
                          )
                        """,
                        (
                            experiment_id,
                            start_ns,
                            end_ns,
                        ),
                    ).fetchone()[0]
                )
    finally:
        connection.close()

    checks: list[QualityCheck] = []

    def add_check(
        key: str,
        title: str,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            QualityCheck(
                key=key,
                title=title,
                status=status,
                message=message,
                details=details or {},
            )
        )

    duration_ns = None
    if end_ns is not None:
        duration_ns = end_ns - start_ns
    complete = (
        experiment.get("status") == "complete"
        and duration_ns is not None
        and duration_ns >= 0
    )
    add_check(
        "experiment_lifecycle",
        "Experiment lifecycle",
        PASS if complete else FAIL,
        (
            f"Complete session; duration "
            f"{duration_ns / 1_000_000_000:.3f} seconds."
            if complete
            else "Experiment is not cleanly marked complete."
        ),
    )

    add_check(
        "controller_stream",
        "Controller stream",
        PASS
        if counts["controller_samples"] > 0
        else FAIL,
        f"{counts['controller_samples']:,} controller samples recorded.",
    )
    add_check(
        "mavlink_stream",
        "MAVLink stream",
        PASS
        if counts["mavlink_messages"] > 0
        else FAIL,
        f"{counts['mavlink_messages']:,} MAVLink messages recorded.",
    )
    add_check(
        "mavlink_heartbeat",
        "MAVLink heartbeat",
        PASS
        if counts["heartbeats"] > 0
        else FAIL,
        f"{counts['heartbeats']:,} HEARTBEAT messages recorded.",
    )
    add_check(
        "mavlink_raw_hex",
        "MAVLink raw bytes",
        PASS
        if counts["mavlink_messages"] > 0
        and counts["missing_raw_hex"] == 0
        else FAIL,
        (
            "No MAVLink messages were recorded."
            if counts["mavlink_messages"] == 0
            else "Every saved MAVLink message includes raw hexadecimal bytes."
            if counts["missing_raw_hex"] == 0
            else f"{counts['missing_raw_hex']:,} MAVLink message(s) lack raw hex."
        ),
        {
            "manual_control_tx": counts["manual_control_tx"],
            "rc_channel_rx": counts["rc_channel_rx"],
            "servo_output_rx": counts["servo_output_rx"],
        },
    )

    captures: dict[str, dict[str, Any]] = {}
    for sdr_row in sdr_rows:
        raw_path = str(
            sdr_row["iq_file"] or ""
        )
        if not raw_path:
            continue
        capture = captures.setdefault(
            raw_path,
            {
                "starts": 0,
                "stops": 0,
                "return_codes": [],
                "recorded_sizes": [],
                "metadata_errors": [],
            },
        )
        kind = str(sdr_row["record_kind"])
        if kind == "CAPTURE_START":
            capture["starts"] += 1
        elif kind == "CAPTURE_STOP":
            capture["stops"] += 1

        try:
            metadata = json.loads(
                sdr_row["metadata_json"] or "{}"
            )
        except (TypeError, json.JSONDecodeError):
            metadata = {}
            capture["metadata_errors"].append(
                f"{kind} metadata is not valid JSON"
            )
        if not isinstance(metadata, dict):
            metadata = {}
            capture["metadata_errors"].append(
                f"{kind} metadata is not an object"
            )
        if kind == "CAPTURE_STOP":
            if metadata.get("return_code") is not None:
                try:
                    capture["return_codes"].append(
                        int(metadata["return_code"])
                    )
                except (TypeError, ValueError):
                    capture["metadata_errors"].append(
                        "CAPTURE_STOP return code is invalid"
                    )
            if metadata.get("file_size_bytes") is not None:
                try:
                    recorded_size = int(
                        metadata["file_size_bytes"]
                    )
                except (TypeError, ValueError):
                    capture["metadata_errors"].append(
                        "CAPTURE_STOP file size is invalid"
                    )
                else:
                    if recorded_size < 0:
                        capture["metadata_errors"].append(
                            "CAPTURE_STOP file size is negative"
                        )
                    else:
                        capture["recorded_sizes"].append(
                            recorded_size
                        )

    lifecycle_errors = []
    for raw_path, capture in captures.items():
        lifecycle_errors.extend(
            f"{raw_path}: {error}"
            for error in capture["metadata_errors"]
        )
        if (
            capture["starts"] != 1
            or capture["stops"] != 1
        ):
            lifecycle_errors.append(
                raw_path
            )
        if any(
            code != 0
            for code in capture["return_codes"]
        ):
            lifecycle_errors.append(
                f"{raw_path} returned non-zero"
            )
        if (
            capture["stops"] > 0
            and not capture["return_codes"]
        ):
            lifecycle_errors.append(
                f"{raw_path} has no return code"
            )
    sdr_valid = (
        bool(captures)
        and not lifecycle_errors
    )
    add_check(
        "sdr_lifecycle",
        "SDR capture lifecycle",
        PASS if sdr_valid else FAIL,
        (
            f"{len(captures)} IQ capture(s) have matching "
            "start/stop records and successful return codes."
            if sdr_valid
            else "SDR capture records are missing, unmatched, or unsuccessful."
        ),
        {"errors": lifecycle_errors},
    )

    iq_files = []
    missing_iq = []
    empty_iq = []
    size_mismatches = []
    missing_recorded_sizes = []
    for raw_path, capture in captures.items():
        resolved = _resolve_iq_file(
            raw_path,
            database_path=database_path,
            iq_root=iq_root,
            experiment_id=experiment_id,
            package_directory=package_directory,
        )
        exists = resolved.is_file()
        actual_size = (
            resolved.stat().st_size
            if exists
            else None
        )
        recorded_size = (
            capture["recorded_sizes"][-1]
            if capture["recorded_sizes"]
            else None
        )
        if not exists:
            missing_iq.append(raw_path)
        elif actual_size == 0:
            empty_iq.append(raw_path)
        if (
            actual_size is not None
            and recorded_size is not None
            and actual_size != recorded_size
        ):
            size_mismatches.append(raw_path)
        if recorded_size is None:
            missing_recorded_sizes.append(
                raw_path
            )
        iq_files.append(
            {
                "stored_path": raw_path,
                "resolved_path": str(resolved),
                "exists": exists,
                "actual_size_bytes": actual_size,
                "recorded_size_bytes": recorded_size,
            }
        )

    iq_valid = (
        bool(iq_files)
        and not missing_iq
        and not empty_iq
        and not size_mismatches
        and not missing_recorded_sizes
    )
    add_check(
        "iq_files",
        "IQ files",
        PASS if iq_valid else FAIL,
        (
            f"{len(iq_files)} IQ file(s) exist, are non-empty, "
            "and match recorded sizes."
            if iq_valid
            else "One or more IQ files are missing, empty, or have a size mismatch."
        ),
        {
            "missing": missing_iq,
            "empty": empty_iq,
            "size_mismatches": size_mismatches,
            "missing_recorded_sizes": (
                missing_recorded_sizes
            ),
        },
    )

    guided_events = (
        guided_trials["started_event_count"]
        + guided_trials["ended_event_count"]
    )
    pairing_errors = sum(
        int(guided_trials[key])
        for key in (
            "incomplete_trial_count",
            "invalid_event_count",
            "duplicate_event_count",
            "invalid_duration_count",
        )
    )
    if guided_events == 0:
        pairing_status = WARNING
        pairing_message = (
            "No guided action intervals were recorded."
        )
    elif pairing_errors:
        pairing_status = FAIL
        pairing_message = (
            f"Guided trials contain {pairing_errors} pairing or data error(s)."
        )
    else:
        pairing_status = PASS
        pairing_message = (
            f"{guided_trials['complete_trial_count']} guided trial(s) "
            "have valid START/END pairs."
        )
    add_check(
        "guided_pairing",
        "Guided trial pairing",
        pairing_status,
        pairing_message,
    )

    package_metadata = None
    session_info = None
    package_errors = []
    if package_directory is None:
        package_errors.append(
            "No package directory matches the experiment ID."
        )
    else:
        for name in REQUIRED_PACKAGE_FILES:
            if not (
                package_directory / name
            ).exists():
                package_errors.append(
                    f"Missing {name}"
                )
        package_metadata, metadata_error = _read_json(
            package_directory / "metadata.json"
        )
        session_info, session_error = _read_json(
            package_directory / "session_info.json"
        )
        if metadata_error:
            package_errors.append(
                f"metadata.json: {metadata_error}"
            )
        if session_error:
            package_errors.append(
                f"session_info.json: {session_error}"
            )
        if package_metadata is not None:
            package_id = (
                package_metadata.get("id")
                or package_metadata.get(
                    "experiment_id"
                )
            )
            if package_id != experiment_id:
                package_errors.append(
                    "Package experiment ID does not match SQLite."
                )
            if (
                package_metadata.get("status")
                != "complete"
            ):
                package_errors.append(
                    "Package metadata is not marked complete."
                )
    add_check(
        "experiment_package",
        "Experiment package",
        PASS if not package_errors else FAIL,
        (
            "Package metadata, configuration, notes, and IQ reference are complete."
            if not package_errors
            else "; ".join(package_errors)
        ),
    )

    export_errors = []
    export_summary = None
    if export_directory is None:
        export_errors.append(
            "No export directory matches the experiment ID."
        )
    else:
        for name in REQUIRED_EXPORT_FILES:
            path = export_directory / name
            if not path.is_file():
                export_errors.append(
                    f"Missing {name}"
                )
        temporary_files = sorted(
            path.name
            for path in export_directory.glob(
                "*.tmp"
            )
        )
        if temporary_files:
            export_errors.append(
                "Unfinished temporary exports: "
                + ", ".join(temporary_files)
            )
        export_summary, summary_error = _read_json(
            export_directory
            / "experiment_summary.json"
        )
        if summary_error:
            export_errors.append(
                "experiment_summary.json: "
                f"{summary_error}"
            )
        if export_summary is not None:
            summary_experiment = export_summary.get(
                "experiment",
                {},
            )
            if not isinstance(
                summary_experiment,
                dict,
            ):
                export_errors.append(
                    "Export experiment metadata is not an object."
                )
            elif (
                summary_experiment.get("id")
                != experiment_id
            ):
                export_errors.append(
                    "Export experiment ID does not match SQLite."
                )
            expected_counts = {
                "controller_samples.csv": counts[
                    "controller_samples"
                ],
                "mavlink_messages.csv": counts[
                    "mavlink_messages"
                ],
                "events.csv": counts["events"],
                "sdr_records.csv": counts[
                    "sdr_records"
                ],
            }
            summary_counts = export_summary.get(
                "row_counts",
                {},
            )
            if summary_counts != expected_counts:
                export_errors.append(
                    "Export row counts do not match SQLite."
                )
    add_check(
        "automatic_exports",
        "Automatic exports",
        PASS if not export_errors else FAIL,
        (
            "All required exports exist and row counts match SQLite."
            if not export_errors
            else "; ".join(export_errors)
        ),
    )

    target_repetitions = guided_trials.get(
        "target_repetitions"
    )
    planned_actions = list(GUIDED_ACTIONS)
    if session_info is not None:
        guided_configuration = session_info.get(
            "guided_trials",
            {},
        )
        if isinstance(
            guided_configuration,
            dict,
        ):
            configured_actions = guided_configuration.get(
                "actions"
            )
            if isinstance(
                configured_actions,
                list,
            ) and configured_actions:
                planned_actions = [
                    str(action)
                    for action in configured_actions
                ]
            try:
                configured_target = int(
                    guided_configuration.get(
                        "target_repetitions"
                    )
                )
            except (TypeError, ValueError):
                configured_target = 0
            if configured_target > 0:
                target_repetitions = (
                    configured_target
                )

    guided_trials["target_repetitions"] = (
        target_repetitions
    )
    guided_trials["planned_actions"] = (
        planned_actions
    )
    coverage = {}
    if target_repetitions:
        coverage = {
            action: {
                "completed": guided_trials[
                    "completed_by_action"
                ].get(action, 0),
                "target": target_repetitions,
            }
            for action in planned_actions
        }
    guided_trials["coverage"] = coverage

    if not target_repetitions:
        coverage_status = WARNING
        coverage_message = (
            "No guided repetition target was available."
        )
    else:
        completed_total = sum(
            item["completed"]
            for item in coverage.values()
        )
        target_total = (
            len(coverage)
            * target_repetitions
        )
        incomplete_actions = [
            action
            for action, item in coverage.items()
            if item["completed"] < item["target"]
        ]
        if incomplete_actions:
            coverage_status = WARNING
            coverage_message = (
                f"{completed_total}/{target_total} planned guided trials "
                f"are complete; {len(incomplete_actions)} action(s) "
                "remain below target."
            )
        else:
            coverage_status = PASS
            coverage_message = (
                f"All {target_total} planned guided trials are complete."
            )
    add_check(
        "guided_coverage",
        "Guided trial coverage",
        coverage_status,
        coverage_message,
        {"coverage": coverage},
    )

    mapping_complete = False
    if session_info is not None:
        mapping = session_info.get(
            "controller_mapping",
            {},
        )
        if isinstance(mapping, dict):
            mapping_complete = all(
                mapping.get(control) is not None
                for control in (
                    "roll",
                    "pitch",
                    "yaw",
                    "throttle",
                )
            )
    add_check(
        "controller_mapping",
        "Controller mapping snapshot",
        PASS if mapping_complete else WARNING,
        (
            "Roll, pitch, yaw, and throttle mappings were captured."
            if mapping_complete
            else "The package does not contain all four primary control mappings."
        ),
    )

    add_check(
        "timestamp_bounds",
        "Timestamp bounds",
        PASS if out_of_bounds == 0 else FAIL,
        (
            "All structured records fall within the experiment interval."
            if out_of_bounds == 0
            else f"{out_of_bounds} record(s) fall outside the experiment interval."
        ),
    )

    return SessionQualityReport(
        experiment=experiment,
        counts=counts,
        guided_trials=guided_trials,
        iq_files=tuple(iq_files),
        package_directory=(
            str(package_directory)
            if package_directory is not None
            else None
        ),
        export_directory=(
            str(export_directory)
            if export_directory is not None
            else None
        ),
        checks=tuple(checks),
        generated_utc=datetime.now(
            timezone.utc
        ).isoformat(),
    )

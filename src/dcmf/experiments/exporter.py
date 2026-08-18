"""Filtered per-experiment exports from the DCMF SQLite recorder."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QThread, Signal

from dcmf.core.guided_trials import GUIDED_ACTIONS
from dcmf.experiments.packaging import (
    ExperimentPackage,
    finalize_experiment_package,
)


EXPORT_QUERIES = {
    "controller_samples.csv": """
        SELECT
            c.id,
            c.experiment_id,
            c.monotonic_ns,
            c.utc_ns,
            c.device_name,
            c.axes_json,
            c.buttons_json,
            c.hats_json,
            json_extract(e.payload_json, '$.mapped.roll')
                AS mapped_roll,
            json_extract(e.payload_json, '$.mapped.pitch')
                AS mapped_pitch,
            json_extract(e.payload_json, '$.mapped.yaw')
                AS mapped_yaw,
            json_extract(e.payload_json, '$.mapped.throttle')
                AS mapped_throttle
        FROM controller_samples AS c
        LEFT JOIN events AS e
            ON e.experiment_id = c.experiment_id
            AND e.monotonic_ns = c.monotonic_ns
            AND e.source = 'CONTROLLER'
            AND e.kind = 'SAMPLE'
        WHERE c.experiment_id = ?
        ORDER BY c.monotonic_ns, c.id
    """,
    "mavlink_messages.csv": """
        SELECT
            id,
            experiment_id,
            monotonic_ns,
            utc_ns,
            direction,
            message_name,
            message_id,
            system_id,
            component_id,
            raw_hex,
            decoded_json
        FROM mavlink_messages
        WHERE experiment_id = ?
        ORDER BY monotonic_ns, id
    """,
    "events.csv": """
        SELECT
            id,
            experiment_id,
            monotonic_ns,
            utc_ns,
            source,
            kind,
            payload_json
        FROM events
        WHERE experiment_id = ?
        ORDER BY monotonic_ns, id
    """,
    "sdr_records.csv": """
        SELECT
            id,
            experiment_id,
            monotonic_ns,
            utc_ns,
            record_kind,
            center_frequency_hz,
            sample_rate_hz,
            gain_db,
            power_dbfs,
            iq_file,
            metadata_json
        FROM sdr_records
        WHERE experiment_id = ?
        ORDER BY monotonic_ns, id
    """,
}


def _utc_iso(utc_ns: int | None) -> str | None:
    if utc_ns is None:
        return None
    return datetime.fromtimestamp(
        utc_ns / 1_000_000_000,
        tz=timezone.utc,
    ).isoformat()


def _write_csv(
    path: Path,
    columns: Iterable[str],
    rows: Iterable[sqlite3.Row],
) -> int:
    """Write query rows atomically and return the row count."""
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )
    count = 0

    with temporary.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)

        for row in rows:
            writer.writerow(tuple(row))
            count += 1

    temporary.replace(path)
    return count


def _write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
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


def _guided_trial_summary(
    connection: sqlite3.Connection,
    experiment_id: str,
) -> dict[str, Any]:
    """Pair ACTION_START/ACTION_END events into numbered trials."""
    rows = connection.execute(
        """
        SELECT
            monotonic_ns,
            utc_ns,
            kind,
            payload_json
        FROM events
        WHERE experiment_id = ?
          AND source = 'OPERATOR'
          AND kind IN ('ACTION_START', 'ACTION_END')
        ORDER BY monotonic_ns, id
        """,
        (experiment_id,),
    )

    pairs: dict[
        tuple[str, int],
        dict[str, Any],
    ] = {}
    action_counts: dict[
        str,
        dict[str, int],
    ] = {
        action: {
            "started": 0,
            "ended": 0,
            "completed": 0,
        }
        for action in GUIDED_ACTIONS
    }
    target_repetitions: set[int] = set()
    invalid_event_count = 0
    duplicate_event_count = 0
    automatic_end_count = 0
    started_event_count = 0
    ended_event_count = 0

    for row in rows:
        kind = str(row["kind"])
        if kind == "ACTION_START":
            started_event_count += 1
            slot = "start"
        else:
            ended_event_count += 1
            slot = "end"

        try:
            payload = json.loads(
                row["payload_json"] or "{}"
            )
        except (TypeError, json.JSONDecodeError):
            invalid_event_count += 1
            continue

        action = str(
            payload.get("action") or ""
        ).strip()
        raw_trial_number = payload.get(
            "trial_number",
            payload.get("trial"),
        )

        try:
            trial_number = int(raw_trial_number)
        except (TypeError, ValueError):
            invalid_event_count += 1
            continue

        if not action or trial_number < 1:
            invalid_event_count += 1
            continue

        raw_target = payload.get(
            "target_repetitions"
        )
        try:
            target = int(raw_target)
        except (TypeError, ValueError):
            target = 0
        if target > 0:
            target_repetitions.add(target)

        counts = action_counts.setdefault(
            action,
            {
                "started": 0,
                "ended": 0,
                "completed": 0,
            },
        )
        counts[
            "started" if slot == "start" else "ended"
        ] += 1

        event_details = {
            "label": payload.get(
                "label",
                f"{action}_{slot.upper()}",
            ),
            "monotonic_ns": row["monotonic_ns"],
            "utc_ns": row["utc_ns"],
            "utc_iso": _utc_iso(row["utc_ns"]),
        }
        if slot == "end":
            automatic = bool(
                payload.get("automatic", False)
            )
            event_details["automatic"] = automatic
            if automatic:
                automatic_end_count += 1

        pair = pairs.setdefault(
            (action, trial_number),
            {
                "action": action,
                "trial_number": trial_number,
                "start": None,
                "end": None,
            },
        )
        if pair[slot] is not None:
            duplicate_event_count += 1
        else:
            pair[slot] = event_details

    action_order = {
        action: index
        for index, action in enumerate(
            GUIDED_ACTIONS
        )
    }
    ordered_pairs = sorted(
        pairs.values(),
        key=lambda item: (
            action_order.get(
                item["action"],
                len(action_order),
            ),
            item["action"],
            item["trial_number"],
        ),
    )

    complete_trial_count = 0
    incomplete_trial_count = 0
    trials: list[dict[str, Any]] = []

    for pair in ordered_pairs:
        start = pair["start"]
        end = pair["end"]
        complete = start is not None and end is not None
        duration_ns = None

        if complete:
            complete_trial_count += 1
            action_counts[pair["action"]][
                "completed"
            ] += 1
            duration_ns = (
                end["monotonic_ns"]
                - start["monotonic_ns"]
            )
            status = "complete"
        elif start is None:
            incomplete_trial_count += 1
            status = "missing_start"
        else:
            incomplete_trial_count += 1
            status = "missing_end"

        trials.append(
            {
                **pair,
                "status": status,
                "duration_ns": duration_ns,
                "duration_seconds": (
                    duration_ns / 1_000_000_000
                    if duration_ns is not None
                    else None
                ),
            }
        )

    targets = sorted(target_repetitions)
    return {
        "actions": list(GUIDED_ACTIONS),
        "target_repetitions": (
            targets[0]
            if len(targets) == 1
            else None
        ),
        "observed_target_repetitions": targets,
        "started_event_count": started_event_count,
        "ended_event_count": ended_event_count,
        "complete_trial_count": complete_trial_count,
        "incomplete_trial_count": incomplete_trial_count,
        "automatic_end_count": automatic_end_count,
        "invalid_event_count": invalid_event_count,
        "duplicate_event_count": duplicate_event_count,
        "by_action": action_counts,
        "trials": trials,
    }


def export_experiment(
    database_path: Path,
    package: ExperimentPackage,
) -> dict[str, Any]:
    """Export only ``package.experiment_id`` from SQLite."""
    database_path = Path(database_path).resolve()
    package.export_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        f"file:{database_path}?mode=ro",
        uri=True,
        timeout=10.0,
    )
    connection.row_factory = sqlite3.Row

    try:
        experiment_row = connection.execute(
            """
            SELECT *
            FROM experiments
            WHERE id = ?
            """,
            (package.experiment_id,),
        ).fetchone()

        if experiment_row is None:
            raise RuntimeError(
                "Experiment was not found in SQLite: "
                f"{package.experiment_id}"
            )

        experiment = dict(experiment_row)
        if experiment.get("status") != "complete":
            raise RuntimeError(
                "Experiment is not complete and cannot be exported: "
                f"{package.experiment_id}"
            )

        counts: dict[str, int] = {}

        for file_name, query in EXPORT_QUERIES.items():
            cursor = connection.execute(
                query,
                (package.experiment_id,),
            )
            columns = [
                item[0]
                for item in cursor.description
            ]
            counts[file_name] = _write_csv(
                package.export_directory / file_name,
                columns,
                cursor,
            )

        iq_files = [
            str(row["iq_file"])
            for row in connection.execute(
                """
                SELECT DISTINCT iq_file
                FROM sdr_records
                WHERE experiment_id = ?
                  AND iq_file IS NOT NULL
                  AND iq_file != ''
                ORDER BY iq_file
                """,
                (package.experiment_id,),
            )
        ]
        guided_trials = _guided_trial_summary(
            connection,
            package.experiment_id,
        )

        duration_ns = None
        if (
            experiment.get("ended_monotonic_ns")
            is not None
        ):
            duration_ns = (
                experiment["ended_monotonic_ns"]
                - experiment["started_monotonic_ns"]
            )

        summary_experiment = {
            **experiment,
            "started_utc_iso": _utc_iso(
                experiment.get("started_utc_ns")
            ),
            "ended_utc_iso": _utc_iso(
                experiment.get("ended_utc_ns")
            ),
        }
        summary = {
            "experiment": summary_experiment,
            "duration_ns": duration_ns,
            "duration_seconds": (
                duration_ns / 1_000_000_000
                if duration_ns is not None
                else None
            ),
            "row_counts": counts,
            "iq_files": iq_files,
            "guided_trials": guided_trials,
            "package_directory": str(
                package.package_directory
            ),
            "export_directory": str(
                package.export_directory
            ),
            "generated_utc": datetime.now(
                timezone.utc
            ).isoformat(),
        }
        _write_json(
            package.export_directory
            / "experiment_summary.json",
            summary,
        )

        finalize_experiment_package(
            package,
            experiment,
            iq_files,
        )

        return {
            "experiment_id": package.experiment_id,
            "export_directory": str(
                package.export_directory
            ),
            "row_counts": counts,
        }
    finally:
        connection.close()


class ExperimentExportWorker(QThread):
    """Run CSV/JSON export without blocking the Qt GUI thread."""

    export_completed = Signal(object)
    export_failed = Signal(str, str)

    def __init__(
        self,
        database_path: Path,
        package: ExperimentPackage,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.database_path = Path(database_path)
        self.package = package

    def run(self) -> None:
        try:
            result = export_experiment(
                self.database_path,
                self.package,
            )
        except Exception as exc:
            self.export_failed.emit(
                self.package.experiment_id,
                str(exc),
            )
            return

        self.export_completed.emit(result)

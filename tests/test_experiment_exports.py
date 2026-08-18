"""Focused tests for Milestone 7 packaging and exports."""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dcmf.database.schema import SCHEMA_SQL
from dcmf.experiments.exporter import export_experiment
from dcmf.experiments.packaging import (
    create_experiment_package,
)
from dcmf.utils.timestamps import Timestamp


class ExperimentExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        self.root = Path(
            self.temporary_directory.name
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_package(
        self,
        experiment_id: str = "target-id",
    ):
        return create_experiment_package(
            experiment_root=self.root / "experiments",
            export_root=self.root / "exports",
            iq_root=self.root / "data" / "iq",
            experiment_id=experiment_id,
            metadata={
                "name": "Flight Test / One",
                "operator": "operator",
                "notes": "bench validation",
            },
            timestamp=Timestamp(
                monotonic_ns=1_000,
                utc_ns=1_700_000_000_000_000_000,
            ),
            application_name="DCMF",
            application_version="test",
            database_path=self.root / "data" / "dcmf.sqlite3",
            controller_mapping={
                "roll": {
                    "axis_index": 0,
                    "inverted": False,
                },
            },
            mavlink_configuration={
                "port": "/dev/ttyUSB0",
                "baud": 57600,
            },
            sdr_configuration={
                "center_frequency_hz": 915_000_000,
            },
            guided_trial_configuration={
                "actions": [
                    "ROLL_RIGHT",
                    "ROLL_LEFT",
                ],
                "target_repetitions": 3,
                "labeling": "START_END_INTERVALS",
            },
        )

    def _create_database(self) -> Path:
        database_path = (
            self.root / "data" / "dcmf.sqlite3"
        )
        database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        connection = sqlite3.connect(database_path)
        connection.executescript(SCHEMA_SQL)

        for experiment_id, name in (
            ("target-id", "Target"),
            ("other-id", "Other"),
        ):
            connection.execute(
                """
                INSERT INTO experiments (
                    id,
                    name,
                    operator,
                    notes,
                    started_monotonic_ns,
                    started_utc_ns,
                    ended_monotonic_ns,
                    ended_utc_ns,
                    status
                )
                VALUES (?, ?, '', '', 1000, 2000, 3000, 4000, 'complete')
                """,
                (experiment_id, name),
            )
            connection.execute(
                """
                INSERT INTO events (
                    experiment_id,
                    monotonic_ns,
                    utc_ns,
                    source,
                    kind,
                    payload_json
                )
                VALUES (?, 1100, 2100, 'CONTROLLER', 'SAMPLE', ?)
                """,
                (
                    experiment_id,
                    json.dumps(
                        {
                            "mapped": {
                                "roll": 0.75,
                                "pitch": 0.0,
                                "yaw": 0.0,
                                "throttle": -1.0,
                            }
                        }
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO controller_samples (
                    experiment_id,
                    monotonic_ns,
                    utc_ns,
                    device_name,
                    axes_json,
                    buttons_json,
                    hats_json
                )
                VALUES (?, 1100, 2100, 'TX16S', '[0.75]', '[]', '[]')
                """,
                (experiment_id,),
            )
            for kind, monotonic_ns, label in (
                (
                    "ACTION_START",
                    1150,
                    "ROLL_RIGHT_START",
                ),
                (
                    "ACTION_END",
                    1175,
                    "ROLL_RIGHT_END",
                ),
            ):
                connection.execute(
                    """
                    INSERT INTO events (
                        experiment_id,
                        monotonic_ns,
                        utc_ns,
                        source,
                        kind,
                        payload_json
                    )
                    VALUES (?, ?, ?, 'OPERATOR', ?, ?)
                    """,
                    (
                        experiment_id,
                        monotonic_ns,
                        monotonic_ns + 1_000,
                        kind,
                        json.dumps(
                            {
                                "label": label,
                                "action": "ROLL_RIGHT",
                                "trial_number": 1,
                                "target_repetitions": 3,
                                "automatic": False,
                            }
                        ),
                    ),
                )
            connection.execute(
                """
                INSERT INTO mavlink_messages (
                    experiment_id,
                    monotonic_ns,
                    utc_ns,
                    direction,
                    message_name,
                    raw_hex,
                    decoded_json
                )
                VALUES (?, 1200, 2200, 'RX', 'HEARTBEAT', 'fe 00', '{}')
                """,
                (experiment_id,),
            )
            connection.execute(
                """
                INSERT INTO sdr_records (
                    experiment_id,
                    monotonic_ns,
                    utc_ns,
                    record_kind,
                    iq_file,
                    metadata_json
                )
                VALUES (?, 1300, 2300, 'CAPTURE_STOP', ?, '{}')
                """,
                (
                    experiment_id,
                    f"data/iq/{experiment_id}/capture.sc16",
                ),
            )

        connection.commit()
        connection.close()
        return database_path

    def test_package_contains_snapshots_and_iq_reference(
        self,
    ) -> None:
        package = self._create_package()

        self.assertTrue(
            package.package_directory.is_dir()
        )
        self.assertEqual(
            package.folder_name,
            "2023-11-14_221320_Flight-Test-One",
        )
        self.assertTrue(
            (package.package_directory / "metadata.json").is_file()
        )
        self.assertTrue(
            (package.package_directory / "session_info.json").is_file()
        )
        self.assertEqual(
            (
                package.package_directory
                / "notes.txt"
            ).read_text(encoding="utf-8"),
            "bench validation\n",
        )
        self.assertTrue(
            (package.package_directory / "iq").is_symlink()
        )
        self.assertTrue(
            (package.package_directory / "iq").is_dir()
        )

        session_info = json.loads(
            (
                package.package_directory
                / "session_info.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            session_info["mavlink"]["baud"],
            57600,
        )
        self.assertFalse(
            session_info["synchronization"][
                "hardware_synchronized"
            ]
        )
        self.assertEqual(
            session_info["guided_trials"][
                "target_repetitions"
            ],
            3,
        )

    def test_export_contains_only_selected_experiment(
        self,
    ) -> None:
        database_path = self._create_database()
        package = self._create_package()

        result = export_experiment(
            database_path,
            package,
        )

        self.assertEqual(
            result["row_counts"],
            {
                "controller_samples.csv": 1,
                "mavlink_messages.csv": 1,
                "events.csv": 3,
                "sdr_records.csv": 1,
            },
        )

        for file_name in (
            "controller_samples.csv",
            "mavlink_messages.csv",
            "events.csv",
            "sdr_records.csv",
            "experiment_summary.json",
        ):
            self.assertTrue(
                (
                    package.export_directory
                    / file_name
                ).is_file()
            )

        with (
            package.export_directory
            / "controller_samples.csv"
        ).open(encoding="utf-8", newline="") as handle:
            rows = list(
                csv.DictReader(handle)
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["experiment_id"],
            "target-id",
        )
        self.assertEqual(
            rows[0]["mapped_roll"],
            "0.75",
        )

        summary = json.loads(
            (
                package.export_directory
                / "experiment_summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            summary["experiment"]["id"],
            "target-id",
        )
        self.assertEqual(
            summary["experiment"]["started_utc_iso"],
            "1970-01-01T00:00:00.000002+00:00",
        )
        self.assertEqual(
            summary["iq_files"],
            ["data/iq/target-id/capture.sc16"],
        )
        self.assertEqual(
            summary["guided_trials"][
                "complete_trial_count"
            ],
            1,
        )
        self.assertEqual(
            summary["guided_trials"]["trials"][0][
                "start"
            ]["label"],
            "ROLL_RIGHT_START",
        )
        self.assertEqual(
            summary["guided_trials"]["trials"][0][
                "end"
            ]["label"],
            "ROLL_RIGHT_END",
        )

        finalized_metadata = json.loads(
            (
                package.package_directory
                / "metadata.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            finalized_metadata["status"],
            "complete",
        )


if __name__ == "__main__":
    unittest.main()

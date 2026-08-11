"""Tests for Milestone 9 read-only session quality review."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dcmf.analysis.session_quality import (
    FAIL,
    PASS,
    WARNING,
    evaluate_session,
    list_experiments,
)
from dcmf.core.guided_trials import GUIDED_ACTIONS
from dcmf.database.schema import SCHEMA_SQL
from dcmf.experiments.exporter import export_experiment
from dcmf.experiments.packaging import (
    create_experiment_package,
)
from dcmf.utils.timestamps import Timestamp


class SessionQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        self.root = Path(
            self.temporary_directory.name
        )
        self.database_path = (
            self.root / "data" / "dcmf.sqlite3"
        )
        self.experiment_id = "quality-session-id"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_valid_session(
        self,
        *,
        target_repetitions: int = 1,
    ):
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        connection = sqlite3.connect(
            self.database_path
        )
        connection.executescript(SCHEMA_SQL)
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
            VALUES (?, 'Quality Session', 'tester', '',
                    1000, 2000, 100000, 101000, 'complete')
            """,
            (self.experiment_id,),
        )

        mapped_payload = json.dumps(
            {
                "mapped": {
                    "roll": 0.5,
                    "pitch": 0.0,
                    "yaw": 0.0,
                    "throttle": -1.0,
                }
            }
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
            VALUES (?, 1500, 2500, 'CONTROLLER', 'SAMPLE', ?)
            """,
            (
                self.experiment_id,
                mapped_payload,
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
            VALUES (?, 1500, 2500, 'TX16S', '[0.5]', '[]', '[]')
            """,
            (self.experiment_id,),
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
            VALUES (?, 1600, 2600, 'RX', 'HEARTBEAT', 'fd 00', '{}')
            """,
            (self.experiment_id,),
        )

        monotonic_ns = 2000
        for action in GUIDED_ACTIONS:
            for kind, phase in (
                ("ACTION_START", "START"),
                ("ACTION_END", "END"),
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
                        self.experiment_id,
                        monotonic_ns,
                        monotonic_ns + 1000,
                        kind,
                        json.dumps(
                            {
                                "label": (
                                    f"{action}_{phase}"
                                ),
                                "action": action,
                                "phase": phase,
                                "trial_number": 1,
                                "target_repetitions": (
                                    target_repetitions
                                ),
                                "automatic": False,
                            }
                        ),
                    ),
                )
                monotonic_ns += 100

        package = create_experiment_package(
            experiment_root=(
                self.root / "experiments"
            ),
            export_root=self.root / "exports",
            iq_root=self.root / "data" / "iq",
            experiment_id=self.experiment_id,
            metadata={
                "name": "Quality Session",
                "operator": "tester",
                "notes": "",
            },
            timestamp=Timestamp(
                monotonic_ns=1000,
                utc_ns=2_000,
            ),
            application_name="DCMF",
            application_version="test",
            database_path=self.database_path,
            controller_mapping={
                control: {
                    "axis_index": index,
                    "inverted": False,
                }
                for index, control in enumerate(
                    (
                        "roll",
                        "pitch",
                        "yaw",
                        "throttle",
                    )
                )
            },
            mavlink_configuration={
                "port": "/dev/ttyUSB0",
                "baud": 57600,
                "connected": True,
            },
            sdr_configuration={
                "auto_capture": True,
                "center_frequency_hz": 915_000_000,
            },
            guided_trial_configuration={
                "actions": list(GUIDED_ACTIONS),
                "target_repetitions": (
                    target_repetitions
                ),
                "labeling": "START_END_INTERVALS",
            },
        )
        iq_file = (
            package.iq_source_directory
            / "capture.sc16"
        )
        iq_file.write_bytes(b"\x00" * 128)
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
            VALUES (?, 5000, 6000, 'CAPTURE_START', ?, '{}')
            """,
            (
                self.experiment_id,
                str(iq_file),
            ),
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
            VALUES (?, 6000, 7000, 'CAPTURE_STOP', ?, ?)
            """,
            (
                self.experiment_id,
                str(iq_file),
                json.dumps(
                    {
                        "file_size_bytes": 128,
                        "return_code": 0,
                    }
                ),
            ),
        )
        connection.commit()
        connection.close()

        export_experiment(
            self.database_path,
            package,
        )
        return package, iq_file

    def _evaluate(self):
        return evaluate_session(
            database_path=self.database_path,
            experiment_root=(
                self.root / "experiments"
            ),
            export_root=self.root / "exports",
            iq_root=self.root / "data" / "iq",
            experiment_id=self.experiment_id,
        )

    def test_complete_session_passes_all_checks(
        self,
    ) -> None:
        self._create_valid_session()

        report = self._evaluate()

        self.assertEqual(
            report.overall_status,
            PASS,
        )
        self.assertEqual(
            report.status_counts,
            {
                PASS: 12,
                WARNING: 0,
                FAIL: 0,
            },
        )
        self.assertEqual(
            report.guided_trials[
                "complete_trial_count"
            ],
            len(GUIDED_ACTIONS),
        )
        self.assertEqual(
            len(report.iq_files),
            1,
        )

        experiments = list_experiments(
            self.database_path
        )
        self.assertEqual(
            experiments[0]["id"],
            self.experiment_id,
        )

    def test_incomplete_planned_coverage_is_warning(
        self,
    ) -> None:
        self._create_valid_session(
            target_repetitions=2
        )

        report = self._evaluate()
        checks = {
            check.key: check
            for check in report.checks
        }

        self.assertEqual(
            report.overall_status,
            WARNING,
        )
        self.assertEqual(
            checks["guided_pairing"].status,
            PASS,
        )
        self.assertEqual(
            checks["guided_coverage"].status,
            WARNING,
        )

    def test_missing_iq_incomplete_trial_and_export_fail(
        self,
    ) -> None:
        package, iq_file = (
            self._create_valid_session()
        )
        iq_file.unlink()
        (
            package.export_directory
            / "mavlink_messages.csv"
        ).unlink()

        connection = sqlite3.connect(
            self.database_path
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
            VALUES (?, 8000, 9000, 'OPERATOR', 'ACTION_START', ?)
            """,
            (
                self.experiment_id,
                json.dumps(
                    {
                        "action": "ROLL_RIGHT",
                        "trial_number": 2,
                        "target_repetitions": 1,
                    }
                ),
            ),
        )
        connection.commit()
        connection.close()

        report = self._evaluate()
        checks = {
            check.key: check
            for check in report.checks
        }

        self.assertEqual(
            report.overall_status,
            FAIL,
        )
        self.assertEqual(
            checks["iq_files"].status,
            FAIL,
        )
        self.assertEqual(
            checks["guided_pairing"].status,
            FAIL,
        )
        self.assertEqual(
            checks["automatic_exports"].status,
            FAIL,
        )

    def test_malformed_metadata_is_reported_without_crashing(
        self,
    ) -> None:
        self._create_valid_session()

        connection = sqlite3.connect(
            self.database_path
        )
        connection.execute(
            """
            UPDATE sdr_records
            SET metadata_json = ?
            WHERE experiment_id = ?
              AND record_kind = 'CAPTURE_STOP'
            """,
            (
                json.dumps(
                    {
                        "file_size_bytes": "not-a-size",
                        "return_code": "not-a-code",
                    }
                ),
                self.experiment_id,
            ),
        )
        connection.execute(
            """
            UPDATE events
            SET payload_json = '[]'
            WHERE id = (
                SELECT id
                FROM events
                WHERE experiment_id = ?
                  AND kind = 'ACTION_START'
                ORDER BY id
                LIMIT 1
            )
            """,
            (self.experiment_id,),
        )
        connection.commit()
        connection.close()

        report = self._evaluate()
        checks = {
            check.key: check
            for check in report.checks
        }

        self.assertEqual(
            checks["sdr_lifecycle"].status,
            FAIL,
        )
        self.assertEqual(
            checks["iq_files"].status,
            FAIL,
        )
        self.assertEqual(
            checks["guided_pairing"].status,
            FAIL,
        )


if __name__ == "__main__":
    unittest.main()

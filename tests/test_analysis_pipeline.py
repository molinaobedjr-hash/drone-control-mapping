"""Synthetic end-to-end tests for Milestones 10–13."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dcmf.analysis.synchronized import (
    analyze_experiment,
    load_session,
    synchronize_session,
)
from dcmf.database.schema import SCHEMA_SQL
from dcmf.ml.classifier import train_random_forest
from dcmf.ml.features import extract_trial_features
from dcmf.replay.session import ReplaySession


class AnalysisPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "data" / "dcmf.sqlite3"
        self.database.parent.mkdir(parents=True)
        self._create_database()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_database(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            """
            INSERT INTO experiments VALUES (
                'exp-1', 'Synthetic', 'tester', '', 1000000000, 2000000000,
                5000000000, 6000000000, 'complete'
            )
            """
        )
        for offset, roll in ((100_000_000, 0.0), (200_000_000, 0.5), (300_000_000, 1.0)):
            payload = json.dumps(
                {
                    "device": "TX16S",
                    "mapped": {
                        "roll": roll,
                        "pitch": 0.0,
                        "yaw": 0.0,
                        "throttle": -1.0,
                    },
                }
            )
            connection.execute(
                "INSERT INTO events (experiment_id, monotonic_ns, utc_ns, source, kind, payload_json) VALUES ('exp-1', ?, ?, 'CONTROLLER', 'SAMPLE', ?)",
                (1_000_000_000 + offset, 2_000_000_000 + offset, payload),
            )
        for kind, timestamp in (("ACTION_START", 1_050_000_000), ("ACTION_END", 1_350_000_000)):
            connection.execute(
                "INSERT INTO events (experiment_id, monotonic_ns, utc_ns, source, kind, payload_json) VALUES ('exp-1', ?, ?, 'OPERATOR', ?, ?)",
                (
                    timestamp,
                    timestamp + 1_000_000_000,
                    kind,
                    json.dumps(
                        {
                            "action": "ROLL_RIGHT",
                            "trial_number": 1,
                            "target_repetitions": 1,
                            "automatic": False,
                        }
                    ),
                ),
            )
        messages = [
            (
                1_205_000_000,
                "TX",
                "MANUAL_CONTROL",
                {"target": 1, "x": 0, "y": 500, "z": 0, "r": 0, "buttons": 0},
            ),
            (
                1_210_000_000,
                "RX",
                "RC_CHANNELS",
                {"chan1_raw": 1750, "chan2_raw": 1500, "chan3_raw": 1000, "chan4_raw": 1500},
            ),
            (
                1_215_000_000,
                "RX",
                "SERVO_OUTPUT_RAW",
                {"port": 0, "servo1_raw": 1200, "servo2_raw": 1300},
            ),
            (
                1_310_000_000,
                "RX",
                "RC_CHANNELS",
                {"chan1_raw": 0, "chan2_raw": 0, "chan3_raw": 0, "chan4_raw": 0},
            ),
        ]
        for timestamp, direction, name, decoded in messages:
            connection.execute(
                """
                INSERT INTO mavlink_messages (
                    experiment_id, monotonic_ns, utc_ns, direction,
                    message_name, message_id, system_id, component_id,
                    raw_hex, decoded_json
                ) VALUES ('exp-1', ?, ?, ?, ?, 1, 1, 1, 'fe 01', ?)
                """,
                (
                    timestamp,
                    timestamp + 1_000_000_000,
                    direction,
                    name,
                    json.dumps(decoded),
                ),
            )
        connection.commit()
        connection.close()

    def test_load_synchronize_replay_and_features(self) -> None:
        session = load_session(self.database, "exp-1")
        self.assertEqual(len(session.controller), 3)
        self.assertEqual(len(session.manual_control), 1)
        self.assertEqual(len(session.servo_outputs), 1)
        self.assertTrue(np.isnan(session.rc_channels.iloc[-1]["ch1"]))

        synchronized = synchronize_session(session, tolerance_ms=250)
        self.assertEqual(len(synchronized), 3)
        self.assertIn("servo_servo1", synchronized)
        self.assertEqual(synchronized.iloc[1]["guided_action"], "ROLL_RIGHT")

        replay = ReplaySession(session)
        snapshot = replay.seek(0.21)
        self.assertAlmostEqual(snapshot.controller["roll"], 0.5)
        self.assertEqual(snapshot.active_trial["action"], "ROLL_RIGHT")

        features = extract_trial_features(
            session, repository_root=self.root, include_iq_power=False
        )
        self.assertEqual(len(features), 1)
        self.assertEqual(features.iloc[0]["action"], "ROLL_RIGHT")
        self.assertEqual(features.iloc[0]["servo_output_count"], 1)

        result = analyze_experiment(
            self.database, "exp-1", self.root / "analysis"
        )
        self.assertTrue(result.synchronized_csv.is_file())
        self.assertTrue(result.summary_json.is_file())

    def test_random_forest_artifacts(self) -> None:
        rows = []
        for experiment in range(4):
            for action_index, action in enumerate(("ROLL_LEFT", "ROLL_RIGHT")):
                for repeat in range(4):
                    rows.append(
                        {
                            "experiment_id": f"exp-{experiment}",
                            "experiment_name": "synthetic",
                            "action": action,
                            "trial_number": repeat + 1,
                            "feature_a": action_index * 10 + repeat * 0.01,
                            "feature_b": action_index * -5 + experiment * 0.01,
                        }
                    )
        dataset = self.root / "features.csv"
        pd.DataFrame(rows).to_csv(dataset, index=False)
        result = train_random_forest(dataset, self.root / "model")
        self.assertEqual(result.status, "complete")
        self.assertTrue(result.model_path.is_file())
        self.assertTrue(result.metrics_path.is_file())
        self.assertTrue((self.root / "model" / "confusion_matrix.png").is_file())


if __name__ == "__main__":
    unittest.main()

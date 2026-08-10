"""Asynchronous SQLite writer for DCMF experiment data."""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from dcmf.core.event_bus import DcmfEvent
from dcmf.database.schema import SCHEMA_SQL
from dcmf.utils.timestamps import Timestamp


class DatabaseWriter:
    """Thread-safe background SQLite recorder."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.logger = logging.getLogger("dcmf.database")
        self._queue: queue.Queue[
            tuple[str, Any]
        ] = queue.Queue()

        self._thread = threading.Thread(
            target=self._worker,
            name="DCMF-DatabaseWriter",
            daemon=True,
        )

        self._running = False
        self._active_experiment_id: str | None = None
        self._lock = threading.Lock()

    @property
    def active_experiment_id(self) -> str | None:
        with self._lock:
            return self._active_experiment_id

    @property
    def is_recording(self) -> bool:
        return self.active_experiment_id is not None

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._thread.start()

    def start_experiment(
        self,
        metadata: dict[str, Any],
        timestamp: Timestamp,
    ) -> str:
        if self.is_recording:
            raise RuntimeError(
                "An experiment is already recording."
            )

        experiment_id = str(uuid.uuid4())

        with self._lock:
            self._active_experiment_id = experiment_id

        self._queue.put(
            (
                "start_experiment",
                {
                    "id": experiment_id,
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
                    "timestamp": timestamp,
                },
            )
        )

        return experiment_id

    def record_event(self, event: DcmfEvent) -> None:
        experiment_id = self.active_experiment_id
        if experiment_id is None:
            return

        self._queue.put(
            (
                "event",
                {
                    "experiment_id": experiment_id,
                    "event": event,
                },
            )
        )

    def stop_experiment(
        self,
        timestamp: Timestamp,
    ) -> str | None:
        with self._lock:
            experiment_id = self._active_experiment_id
            self._active_experiment_id = None

        if experiment_id is None:
            return None

        self._queue.put(
            (
                "stop_experiment",
                {
                    "id": experiment_id,
                    "timestamp": timestamp,
                },
            )
        )

        return experiment_id

    def shutdown(self) -> None:
        if not self._running:
            return

        self._queue.put(("shutdown", None))
        self._thread.join(timeout=5.0)
        self._running = False

    def _worker(self) -> None:
        connection: sqlite3.Connection | None = None

        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=10.0,
            )
            connection.execute(
                "PRAGMA journal_mode=WAL;"
            )
            connection.execute(
                "PRAGMA synchronous=NORMAL;"
            )
            connection.executescript(SCHEMA_SQL)
            connection.commit()

            self.logger.info(
                "SQLite recorder ready: %s",
                self.database_path,
            )

            while True:
                command, payload = self._queue.get()

                try:
                    if command == "shutdown":
                        connection.commit()
                        break

                    if command == "start_experiment":
                        self._insert_experiment(
                            connection,
                            payload,
                        )

                    elif command == "event":
                        self._insert_event(
                            connection,
                            payload["experiment_id"],
                            payload["event"],
                        )

                    elif command == "stop_experiment":
                        self._close_experiment(
                            connection,
                            payload,
                        )

                    connection.commit()

                except Exception:
                    connection.rollback()
                    self.logger.exception(
                        "Database command failed: %s",
                        command,
                    )

                finally:
                    self._queue.task_done()

        except Exception:
            self.logger.exception(
                "Database writer failed to initialize."
            )

        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _insert_experiment(
        connection: sqlite3.Connection,
        payload: dict[str, Any],
    ) -> None:
        timestamp: Timestamp = payload["timestamp"]

        connection.execute(
            """
            INSERT INTO experiments (
                id,
                name,
                operator,
                notes,
                started_monotonic_ns,
                started_utc_ns,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'recording')
            """,
            (
                payload["id"],
                payload["name"],
                payload["operator"],
                payload["notes"],
                timestamp.monotonic_ns,
                timestamp.utc_ns,
            ),
        )

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        event: DcmfEvent,
    ) -> None:
        payload_json = json.dumps(
            self._make_json_safe(
                event.payload
            ),
            separators=(",", ":"),
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
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                event.timestamp.monotonic_ns,
                event.timestamp.utc_ns,
                event.source,
                event.kind,
                payload_json,
            ),
        )

        if (
            event.source == "CONTROLLER"
            and event.kind == "SAMPLE"
        ):
            self._insert_controller_sample(
                connection,
                experiment_id,
                event,
            )

        elif (
            event.source == "MAVLINK"
            and event.kind == "MESSAGE"
        ):
            self._insert_mavlink_message(
                connection,
                experiment_id,
                event,
            )

        elif event.source == "SDR":
            self._insert_sdr_record(
                connection,
                experiment_id,
                event,
            )

    @staticmethod
    def _insert_controller_sample(
        connection: sqlite3.Connection,
        experiment_id: str,
        event: DcmfEvent,
    ) -> None:
        payload = event.payload

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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                event.timestamp.monotonic_ns,
                event.timestamp.utc_ns,
                str(
                    payload.get("device") or ""
                ),
                json.dumps(
                    payload.get("axes", ())
                ),
                json.dumps(
                    payload.get("buttons", ())
                ),
                json.dumps(
                    payload.get("hats", ())
                ),
            ),
        )

    @staticmethod
    def _insert_mavlink_message(
        connection: sqlite3.Connection,
        experiment_id: str,
        event: DcmfEvent,
    ) -> None:
        payload = event.payload

        connection.execute(
            """
            INSERT INTO mavlink_messages (
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
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                event.timestamp.monotonic_ns,
                event.timestamp.utc_ns,
                payload.get("direction"),
                payload.get("message_name"),
                payload.get("message_id"),
                payload.get("system_id"),
                payload.get("component_id"),
                payload.get("raw_hex"),
                json.dumps(
                    payload.get("decoded", {}),
                    separators=(",", ":"),
                    default=str,
                ),
            ),
        )

    def _insert_sdr_record(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        event: DcmfEvent,
    ) -> None:
        payload = (
            event.payload
            if isinstance(event.payload, dict)
            else {}
        )

        connection.execute(
            """
            INSERT INTO sdr_records (
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
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                event.timestamp.monotonic_ns,
                event.timestamp.utc_ns,
                event.kind,
                payload.get(
                    "center_frequency_hz"
                ),
                payload.get("sample_rate_hz"),
                payload.get("gain_db"),
                payload.get("power_dbfs"),
                payload.get("iq_file"),
                json.dumps(
                    self._make_json_safe(payload),
                    separators=(",", ":"),
                ),
            ),
        )

    @staticmethod
    def _close_experiment(
        connection: sqlite3.Connection,
        payload: dict[str, Any],
    ) -> None:
        timestamp: Timestamp = payload["timestamp"]

        connection.execute(
            """
            UPDATE experiments
            SET
                ended_monotonic_ns = ?,
                ended_utc_ns = ?,
                status = 'complete'
            WHERE id = ?
            """,
            (
                timestamp.monotonic_ns,
                timestamp.utc_ns,
                payload["id"],
            ),
        )

    @classmethod
    def _make_json_safe(
        cls,
        value: Any,
    ) -> Any:
        if is_dataclass(value):
            return {
                key: cls._make_json_safe(item)
                for key, item in asdict(value).items()
            }

        if isinstance(value, dict):
            return {
                str(key): cls._make_json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                cls._make_json_safe(item)
                for item in value
            ]

        if isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
                type(None),
            ),
        ):
            return value

        return str(value)

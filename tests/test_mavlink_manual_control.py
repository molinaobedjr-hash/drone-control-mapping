"""Guard and encoding tests for opt-in MANUAL_CONTROL output."""

from __future__ import annotations

import time
import unittest

from pymavlink import mavutil

from dcmf.acquisition.mavlink.reader import (
    GCS_COMPONENT_ID,
    GCS_SYSTEM_ID,
    MavlinkReader,
    mapped_controls_to_manual_control,
)


class _Connection:
    def __init__(self) -> None:
        self.mav = mavutil.mavlink.MAVLink(
            None,
            srcSystem=GCS_SYSTEM_ID,
            srcComponent=GCS_COMPONENT_ID,
        )
        self.writes: list[bytes] = []

    def write(self, raw: bytes) -> None:
        self.writes.append(bytes(raw))


class ManualControlTests(unittest.TestCase):
    def test_normalized_mapping_uses_mavlink_ranges(self) -> None:
        command = mapped_controls_to_manual_control(
            {
                "roll": 0.5,
                "pitch": -0.25,
                "yaw": 0.01,
                "throttle": -1.0,
            }
        )
        self.assertEqual(command.x, -250)
        self.assertEqual(command.y, 500)
        self.assertEqual(command.z, 0)
        self.assertEqual(command.r, 0)
        self.assertEqual(command.buttons, 0)

        high = mapped_controls_to_manual_control(
            {"roll": 2, "pitch": -2, "yaw": 1, "throttle": 1}
        )
        self.assertEqual((high.x, high.y, high.z, high.r), (-1000, 1000, 1000, 1000))

    def test_incomplete_mapping_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            mapped_controls_to_manual_control(
                {"roll": 0, "pitch": 0, "yaw": None, "throttle": -1}
            )

    def test_tx_packet_contains_raw_hex_and_is_suppressed_when_armed(self) -> None:
        reader = MavlinkReader("test", 57600)
        connection = _Connection()
        reader._connection = connection
        with reader._state_lock:
            reader._target_system_id = 1
            reader._vehicle_armed = False
        reader.set_output_enabled(True)
        reader.set_manual_control(
            {"roll": 0.1, "pitch": 0.2, "yaw": -0.3, "throttle": 0.4}
        )
        packet = reader._send_manual_control_if_ready(time.monotonic())
        self.assertIsNotNone(packet)
        self.assertEqual(packet.direction, "TX")
        self.assertEqual(packet.message_name, "MANUAL_CONTROL")
        self.assertTrue(packet.raw_hex)
        self.assertEqual(packet.decoded["target"], 1)
        self.assertEqual(len(connection.writes), 1)

        with reader._state_lock:
            reader._vehicle_armed = True
        self.assertIsNone(reader._send_manual_control_if_ready(time.monotonic()))
        self.assertEqual(len(connection.writes), 1)

    def test_output_gcs_heartbeat_is_also_preserved_as_tx_hex(self) -> None:
        reader = MavlinkReader("test", 57600)
        connection = _Connection()
        reader._connection = connection
        packet = reader._send_gcs_heartbeat()
        self.assertIsNotNone(packet)
        self.assertEqual(packet.direction, "TX")
        self.assertEqual(packet.message_name, "HEARTBEAT")
        self.assertTrue(packet.raw_hex)
        self.assertEqual(connection.writes[0].hex(" "), packet.raw_hex)


if __name__ == "__main__":
    unittest.main()

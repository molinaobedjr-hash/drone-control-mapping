"""Bidirectional MAVLink transport for telemetry capture and control mapping.

The worker owns the serial connection. Incoming messages are always parsed
and emitted. Optional ``MANUAL_CONTROL`` transmission is deliberately
guarded: it is disabled by default, requires a recently supplied mapped
controller sample and an observed vehicle heartbeat, and is suppressed while
the vehicle reports that it is armed.

The telemetry radio presents as a serial device to Linux; MAVLink parsing is
independent of whether the physical transport is an RFD900/SiK-style radio, a
direct USB telemetry cable, or another serial bridge.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from PySide6.QtCore import QThread, Signal
from pymavlink import mavutil
from serial.tools import list_ports


MANUAL_CONTROL_RATE_HZ = 20.0
MANUAL_CONTROL_MAX_AGE_SECONDS = 0.25
GCS_HEARTBEAT_RATE_HZ = 1.0
GCS_SYSTEM_ID = 255
GCS_COMPONENT_ID = 190


@dataclass(slots=True, frozen=True)
class SerialPortInfo:
    """One serial device exposed by the operating system."""

    device: str
    description: str
    manufacturer: str
    product: str
    vid: int | None
    pid: int | None

    @property
    def display_name(self) -> str:
        details = self.description or self.product or "Serial device"
        return f"{self.device} — {details}"


@dataclass(slots=True, frozen=True)
class MavlinkPacket:
    """One parsed inbound or locally generated MAVLink packet."""

    message_name: str
    message_id: int | None
    system_id: int | None
    component_id: int | None
    raw_hex: str
    decoded: dict[str, Any]
    direction: str = "RX"


@dataclass(slots=True, frozen=True)
class ManualControlCommand:
    """Integer fields used by MAVLink ``MANUAL_CONTROL``."""

    x: int
    y: int
    z: int
    r: int
    buttons: int = 0

    def as_dict(self, target: int) -> dict[str, int | str]:
        return {
            "mavpackettype": "MANUAL_CONTROL",
            "target": target,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "r": self.r,
            "buttons": self.buttons,
        }


def _scaled_axis(value: Any, *, deadzone: float) -> int:
    numeric = float(value)
    numeric = max(-1.0, min(1.0, numeric))
    if abs(numeric) < deadzone:
        numeric = 0.0
    return int(round(numeric * 1000.0))


def mapped_controls_to_manual_control(
    mapped: Mapping[str, Any],
    *,
    deadzone: float = 0.02,
) -> ManualControlCommand:
    """Convert normalized DCMF controls to MAVLink field ranges.

    DCMF uses ``[-1, +1]`` for all mapped USB axes. MAVLink uses signed
    ``[-1000, +1000]`` pitch/roll/yaw fields and an unsigned ``[0, 1000]``
    throttle field. No button, arming, or flight-mode command is generated.
    """
    missing = [
        name
        for name in ("roll", "pitch", "yaw", "throttle")
        if mapped.get(name) is None
    ]
    if missing:
        raise ValueError(
            "Mapped controls are incomplete: " + ", ".join(missing)
        )

    throttle = max(-1.0, min(1.0, float(mapped["throttle"])))
    return ManualControlCommand(
        x=_scaled_axis(mapped["pitch"], deadzone=deadzone),
        y=_scaled_axis(mapped["roll"], deadzone=deadzone),
        z=int(round((throttle + 1.0) * 500.0)),
        r=_scaled_axis(mapped["yaw"], deadzone=deadzone),
        buttons=0,
    )


def discover_serial_ports() -> list[SerialPortInfo]:
    """Return currently enumerated serial ports in deterministic order."""
    ports: list[SerialPortInfo] = []

    for port in list_ports.comports():
        ports.append(
            SerialPortInfo(
                device=port.device,
                description=port.description or "",
                manufacturer=port.manufacturer or "",
                product=port.product or "",
                vid=port.vid,
                pid=port.pid,
            )
        )

    return sorted(ports, key=lambda item: item.device)


class MavlinkReader(QThread):
    """Background MAVLink receiver with guarded manual-control output."""

    connection_changed = Signal(bool, str)
    packet_received = Signal(object)
    error_occurred = Signal(str)
    output_state_changed = Signal(str)
    vehicle_state_changed = Signal(object)

    def __init__(
        self,
        port: str,
        baud: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._running = False
        self._connection = None
        self._state_lock = threading.Lock()
        self._output_enabled = False
        self._latest_command: ManualControlCommand | None = None
        self._latest_command_time = 0.0
        self._target_system_id: int | None = None
        self._target_component_id: int | None = None
        self._vehicle_armed: bool | None = None
        self._last_output_state = "Output disabled"

    @property
    def output_enabled(self) -> bool:
        with self._state_lock:
            return self._output_enabled

    @property
    def target_system_id(self) -> int | None:
        with self._state_lock:
            return self._target_system_id

    @property
    def vehicle_armed(self) -> bool | None:
        with self._state_lock:
            return self._vehicle_armed

    def set_output_enabled(self, enabled: bool) -> None:
        """Enable or disable MANUAL_CONTROL generation."""
        with self._state_lock:
            self._output_enabled = bool(enabled)
            if not enabled:
                self._latest_command = None
                self._latest_command_time = 0.0
        self._emit_output_state(
            "Waiting for vehicle heartbeat" if enabled else "Output disabled"
        )

    def set_manual_control(self, mapped: Mapping[str, Any]) -> None:
        """Supply the newest normalized controller values."""
        command = mapped_controls_to_manual_control(mapped)
        with self._state_lock:
            self._latest_command = command
            self._latest_command_time = time.monotonic()

    def stop(self) -> None:
        """Request a clean transport shutdown."""
        self.set_output_enabled(False)
        self._running = False

        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        self.wait(2000)

    def run(self) -> None:
        self._running = True
        last_manual_send = 0.0
        last_heartbeat_send = 0.0

        try:
            self._connection = mavutil.mavlink_connection(
                self.port,
                baud=self.baud,
                autoreconnect=False,
                robust_parsing=True,
                source_system=GCS_SYSTEM_ID,
                source_component=GCS_COMPONENT_ID,
            )

            self.connection_changed.emit(
                True,
                f"{self.port} @ {self.baud} baud",
            )

            while self._running:
                try:
                    message = self._connection.recv_match(
                        blocking=True,
                        timeout=0.02,
                    )
                except Exception as exc:
                    if self._running:
                        self.error_occurred.emit(
                            f"MAVLink receive error: {exc}"
                        )
                    break

                if message is not None and message.get_type() != "BAD_DATA":
                    packet = self._packet_from_message(message)
                    self._observe_vehicle_state(packet)
                    self.packet_received.emit(packet)

                now = time.monotonic()
                if (
                    self.output_enabled
                    and now - last_heartbeat_send
                    >= 1.0 / GCS_HEARTBEAT_RATE_HZ
                ):
                    heartbeat_packet = self._send_gcs_heartbeat()
                    last_heartbeat_send = now
                    if heartbeat_packet is not None:
                        self.packet_received.emit(heartbeat_packet)

                if now - last_manual_send >= 1.0 / MANUAL_CONTROL_RATE_HZ:
                    packet = self._send_manual_control_if_ready(now)
                    last_manual_send = now
                    if packet is not None:
                        self.packet_received.emit(packet)

        except PermissionError as exc:
            self.error_occurred.emit(
                (
                    f"Permission denied opening {self.port}: {exc}. "
                    "Check Linux serial-device permissions."
                )
            )

        except Exception as exc:
            self.error_occurred.emit(
                f"Could not open MAVLink connection: {exc}"
            )

        finally:
            connection = self._connection
            self._connection = None

            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

            with self._state_lock:
                self._output_enabled = False
                self._latest_command = None
            self._running = False
            self._emit_output_state("Output disabled")
            self.connection_changed.emit(False, "Disconnected")

    def _observe_vehicle_state(self, packet: MavlinkPacket) -> None:
        if packet.message_name != "HEARTBEAT" or packet.system_id is None:
            return

        message_type = self._safe_int(packet.decoded.get("type"))
        if message_type == mavutil.mavlink.MAV_TYPE_GCS:
            return

        autopilot = self._safe_int(packet.decoded.get("autopilot"))
        if (
            packet.component_id != mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1
            and autopilot == mavutil.mavlink.MAV_AUTOPILOT_INVALID
        ):
            return

        base_mode = self._safe_int(packet.decoded.get("base_mode")) or 0
        armed = bool(
            base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )

        changed = False
        with self._state_lock:
            if (
                self._target_system_id != packet.system_id
                or self._target_component_id != packet.component_id
                or self._vehicle_armed != armed
            ):
                changed = True
            self._target_system_id = packet.system_id
            self._target_component_id = packet.component_id
            self._vehicle_armed = armed

        if changed:
            self.vehicle_state_changed.emit(
                {
                    "system_id": packet.system_id,
                    "component_id": packet.component_id,
                    "armed": armed,
                }
            )

    def _send_gcs_heartbeat(self) -> MavlinkPacket | None:
        connection = self._connection
        if connection is None:
            return None
        try:
            message = connection.mav.heartbeat_encode(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0,
                0,
                mavutil.mavlink.MAV_STATE_ACTIVE,
            )
            raw = bytes(message.pack(connection.mav))
            connection.write(raw)
        except Exception as exc:
            if self._running:
                self.error_occurred.emit(f"MAVLink heartbeat send error: {exc}")
            return None

        return MavlinkPacket(
            message_name="HEARTBEAT",
            message_id=self._safe_int(message.get_msgId()),
            system_id=GCS_SYSTEM_ID,
            component_id=GCS_COMPONENT_ID,
            raw_hex=raw.hex(" "),
            decoded={
                "mavpackettype": "HEARTBEAT",
                "type": mavutil.mavlink.MAV_TYPE_GCS,
                "autopilot": mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                "base_mode": 0,
                "custom_mode": 0,
                "system_status": mavutil.mavlink.MAV_STATE_ACTIVE,
            },
            direction="TX",
        )

    def _send_manual_control_if_ready(
        self,
        now: float,
    ) -> MavlinkPacket | None:
        connection = self._connection
        if connection is None:
            return None

        with self._state_lock:
            enabled = self._output_enabled
            target = self._target_system_id
            armed = self._vehicle_armed
            command = self._latest_command
            command_age = now - self._latest_command_time

        if not enabled:
            return None
        if target is None:
            self._emit_output_state("Waiting for vehicle heartbeat")
            return None
        if armed is True:
            self._emit_output_state("Suppressed: vehicle reports ARMED")
            return None
        if command is None or command_age > MANUAL_CONTROL_MAX_AGE_SECONDS:
            self._emit_output_state("Waiting for current controller sample")
            return None

        try:
            message = connection.mav.manual_control_encode(
                target,
                command.x,
                command.y,
                command.z,
                command.r,
                command.buttons,
            )
            raw = bytes(message.pack(connection.mav))
            connection.write(raw)
        except Exception as exc:
            self.error_occurred.emit(f"MANUAL_CONTROL send error: {exc}")
            return None

        self._emit_output_state(
            f"Transmitting MANUAL_CONTROL to system {target} at 20 Hz"
        )
        return MavlinkPacket(
            message_name="MANUAL_CONTROL",
            message_id=self._safe_int(message.get_msgId()),
            system_id=GCS_SYSTEM_ID,
            component_id=GCS_COMPONENT_ID,
            raw_hex=raw.hex(" "),
            decoded=self._json_safe(command.as_dict(target)),
            direction="TX",
        )

    def _emit_output_state(self, state: str) -> None:
        if state == self._last_output_state:
            return
        self._last_output_state = state
        self.output_state_changed.emit(state)

    def _packet_from_message(self, message: Any) -> MavlinkPacket:
        try:
            decoded = message.to_dict()
        except Exception:
            decoded = {"message": str(message)}

        try:
            raw = bytes(message.get_msgbuf())
        except Exception:
            raw = b""

        return MavlinkPacket(
            message_name=message.get_type(),
            message_id=self._safe_int(
                self._call_if_present(message, "get_msgId")
            ),
            system_id=self._safe_int(
                self._call_if_present(message, "get_srcSystem")
            ),
            component_id=self._safe_int(
                self._call_if_present(message, "get_srcComponent")
            ),
            raw_hex=raw.hex(" "),
            decoded=self._json_safe(decoded),
            direction="RX",
        )

    @staticmethod
    def _call_if_present(obj: object, name: str) -> Any:
        func = getattr(obj, name, None)
        if callable(func):
            try:
                return func()
            except Exception:
                return None
        return None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]

        if isinstance(value, (str, int, float, bool, type(None))):
            return value

        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

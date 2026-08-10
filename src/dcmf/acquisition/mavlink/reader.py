"""Receive-only MAVLink acquisition through a serial telemetry modem.

This module does not transmit vehicle commands. It opens the selected serial
port, parses incoming MAVLink frames with pymavlink, and emits decoded packet
records to the Qt application.

The telemetry radio presents as a serial device to Linux; MAVLink parsing is
independent of whether the physical transport is an RFD900/SiK radio, a direct
USB telemetry cable, or another serial bridge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QThread, Signal
from serial.tools import list_ports
from pymavlink import mavutil


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
    """One parsed inbound MAVLink packet."""

    message_name: str
    message_id: int | None
    system_id: int | None
    component_id: int | None
    raw_hex: str
    decoded: dict[str, Any]


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
    """Background receive-only MAVLink parser."""

    connection_changed = Signal(bool, str)
    packet_received = Signal(object)
    error_occurred = Signal(str)

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

    def stop(self) -> None:
        """Request a clean reader shutdown."""
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

        try:
            self._connection = mavutil.mavlink_connection(
                self.port,
                baud=self.baud,
                autoreconnect=False,
                robust_parsing=True,
            )

            self.connection_changed.emit(
                True,
                f"{self.port} @ {self.baud} baud",
            )

            while self._running:
                try:
                    message = self._connection.recv_match(
                        blocking=True,
                        timeout=0.25,
                    )
                except Exception as exc:
                    if self._running:
                        self.error_occurred.emit(
                            f"MAVLink receive error: {exc}"
                        )
                    break

                if message is None:
                    continue

                message_name = message.get_type()

                # BAD_DATA is pymavlink's representation of bytes that could
                # not be parsed as a valid MAVLink packet. Do not treat it as
                # normal telemetry.
                if message_name == "BAD_DATA":
                    continue

                try:
                    decoded = message.to_dict()
                except Exception:
                    decoded = {
                        "message": str(message),
                    }

                try:
                    raw = bytes(message.get_msgbuf())
                except Exception:
                    raw = b""

                packet = MavlinkPacket(
                    message_name=message_name,
                    message_id=self._safe_int(
                        self._call_if_present(
                            message,
                            "get_msgId",
                        )
                    ),
                    system_id=self._safe_int(
                        self._call_if_present(
                            message,
                            "get_srcSystem",
                        )
                    ),
                    component_id=self._safe_int(
                        self._call_if_present(
                            message,
                            "get_srcComponent",
                        )
                    ),
                    raw_hex=raw.hex(" "),
                    decoded=self._json_safe(decoded),
                )

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

            self._running = False
            self.connection_changed.emit(
                False,
                "Disconnected",
            )

    @staticmethod
    def _call_if_present(
        obj: object,
        name: str,
    ) -> Any:
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
            return [
                cls._json_safe(item)
                for item in value
            ]

        if isinstance(
            value,
            (str, int, float, bool, type(None)),
        ):
            return value

        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

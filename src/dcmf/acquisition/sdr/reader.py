"""Receive-only UHD/USRP discovery and IQ capture.

The code supports both:
- UHD utilities installed directly in PATH
- Debian/Kali layouts where UHD example binaries live under
  /usr/libexec/uhd/examples/
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal


@dataclass(slots=True, frozen=True)
class UhdDevice:
    """One USRP discovered by `uhd_find_devices`."""

    device_args: str
    product: str
    serial: str
    device_type: str
    name: str

    @property
    def display_name(self) -> str:
        product = self.product or "USRP"
        serial = (
            f" | serial {self.serial}"
            if self.serial
            else ""
        )
        return (
            f"{product}{serial} | "
            f"{self.device_args}"
        )


@dataclass(slots=True, frozen=True)
class SdrCaptureConfig:
    """Configuration for one continuous receive-only IQ capture."""

    device_args: str
    file_path: Path
    center_frequency_hz: int
    sample_rate_hz: int
    gain_db: float
    channel: int = 0
    sample_type: str = "short"


def find_uhd_find_devices() -> str | None:
    """Locate the UHD discovery executable."""
    return shutil.which(
        "uhd_find_devices"
    )


def find_rx_samples_to_file() -> str | None:
    """Locate the UHD receive-to-file example.

    Debian/Kali commonly install UHD examples in /usr/libexec/uhd/examples
    rather than adding them to the shell PATH.
    """
    from_path = shutil.which(
        "rx_samples_to_file"
    )

    if from_path:
        return from_path

    common_paths = (
        Path(
            "/usr/libexec/uhd/examples/"
            "rx_samples_to_file"
        ),
        Path(
            "/usr/lib/uhd/examples/"
            "rx_samples_to_file"
        ),
        Path(
            "/usr/local/libexec/uhd/examples/"
            "rx_samples_to_file"
        ),
        Path(
            "/usr/local/lib/uhd/examples/"
            "rx_samples_to_file"
        ),
    )

    for candidate in common_paths:
        if (
            candidate.is_file()
            and os.access(
                candidate,
                os.X_OK,
            )
        ):
            return str(candidate)

    return None


def uhd_backend_status() -> dict[
    str,
    str | bool | None,
]:
    """Return UHD backend locations and readiness."""
    finder = find_uhd_find_devices()
    capture = find_rx_samples_to_file()

    return {
        "uhd_find_devices": finder,
        "rx_samples_to_file": capture,
        "ready": bool(
            finder and capture
        ),
    }


def discover_uhd_devices() -> list[
    UhdDevice
]:
    """Discover USRPs using the installed UHD utility."""
    executable = find_uhd_find_devices()

    if not executable:
        raise RuntimeError(
            "`uhd_find_devices` was not found."
        )

    result = subprocess.run(
        [executable],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    combined = "\n".join(
        part
        for part in (
            result.stdout,
            result.stderr,
        )
        if part
    )

    # `uhd_find_devices` can print "No UHD Devices Found" while still
    # successfully proving that the UHD backend itself is installed.
    if (
        result.returncode != 0
        and "No UHD Devices Found"
        not in combined
    ):
        raise RuntimeError(
            combined.strip()
            or (
                "uhd_find_devices exited with "
                f"{result.returncode}"
            )
        )

    return _parse_uhd_find_devices(
        combined
    )


def _parse_uhd_find_devices(
    text: str,
) -> list[UhdDevice]:
    """Parse the Device Address blocks printed by UHD."""
    devices: list[UhdDevice] = []

    blocks = re.split(
        r"--\s+UHD Device \d+\s+--",
        text,
    )

    for block in blocks[1:]:
        values: dict[str, str] = {}

        for line in block.splitlines():
            match = re.match(
                (
                    r"\s*([A-Za-z0-9_-]+)"
                    r"\s*:\s*(.*?)\s*$"
                ),
                line,
            )

            if match:
                key, value = match.groups()
                values[
                    key.lower()
                ] = value

        serial = values.get(
            "serial",
            "",
        )
        device_type = values.get(
            "type",
            "",
        )
        product = values.get(
            "product",
            "",
        )
        name = values.get(
            "name",
            "",
        )

        if serial:
            args = f"serial={serial}"
        elif device_type:
            args = (
                f"type={device_type}"
            )
        else:
            args = ""

        devices.append(
            UhdDevice(
                device_args=args,
                product=product,
                serial=serial,
                device_type=device_type,
                name=name,
            )
        )

    return devices


class SdrCaptureWorker(QThread):
    """Run UHD RX capture without blocking the Qt GUI."""

    capture_started = Signal(object)
    capture_stopped = Signal(object)
    output_line = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        config: SdrCaptureConfig,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.config = config
        self._process: (
            subprocess.Popen[str] | None
        ) = None
        self._stop_requested = False

    def stop(self) -> None:
        """Request a clean UHD capture shutdown."""
        self._stop_requested = True
        process = self._process

        if (
            process is not None
            and process.poll() is None
        ):
            try:
                os.killpg(
                    os.getpgid(
                        process.pid
                    ),
                    signal.SIGINT,
                )
            except (
                ProcessLookupError,
                PermissionError,
            ):
                pass

        self.wait(5000)

        process = self._process

        if (
            process is not None
            and process.poll() is None
        ):
            try:
                process.terminate()
                process.wait(
                    timeout=2
                )
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def run(self) -> None:
        capture_program = (
            find_rx_samples_to_file()
        )

        if not capture_program:
            self.error_occurred.emit(
                (
                    "rx_samples_to_file "
                    "could not be located."
                )
            )
            return

        config = self.config

        config.file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            capture_program,
            "--file",
            str(config.file_path),
            "--type",
            config.sample_type,
            "--rate",
            str(
                config.sample_rate_hz
            ),
            "--freq",
            str(
                config.center_frequency_hz
            ),
            "--gain",
            str(config.gain_db),
            "--channels",
            str(config.channel),
            "--progress",
            "--stats",
        ]

        if config.device_args:
            command.extend(
                [
                    "--args",
                    config.device_args,
                ]
            )

        launch_monotonic_ns = (
            time.perf_counter_ns()
        )

        try:
            self._process = (
                subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            )

            self.capture_started.emit(
                {
                    "file":
                        str(
                            config.file_path
                        ),
                    "device_args":
                        config.device_args,
                    "center_frequency_hz":
                        config.center_frequency_hz,
                    "sample_rate_hz":
                        config.sample_rate_hz,
                    "gain_db":
                        config.gain_db,
                    "channel":
                        config.channel,
                    "sample_type":
                        config.sample_type,
                    "capture_backend":
                        capture_program,
                    "process_launch_monotonic_ns":
                        launch_monotonic_ns,
                }
            )

            assert (
                self._process.stdout
                is not None
            )

            for line in (
                self._process.stdout
            ):
                stripped = (
                    line.rstrip()
                )

                if stripped:
                    self.output_line.emit(
                        stripped
                    )

            return_code = (
                self._process.wait()
            )

            file_size = (
                config.file_path.stat().st_size
                if config.file_path.exists()
                else 0
            )

            payload = {
                "file":
                    str(
                        config.file_path
                    ),
                "return_code":
                    return_code,
                "file_size_bytes":
                    file_size,
                "stop_requested":
                    self._stop_requested,
                "capture_backend":
                    capture_program,
            }

            if (
                return_code != 0
                and not self._stop_requested
            ):
                self.error_occurred.emit(
                    (
                        "UHD capture exited "
                        f"with code {return_code}."
                    )
                )

            self.capture_stopped.emit(
                payload
            )

        except Exception as exc:
            self.error_occurred.emit(
                (
                    "SDR capture failed: "
                    f"{exc}"
                )
            )

        finally:
            self._process = None

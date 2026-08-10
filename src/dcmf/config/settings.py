"""Application configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class AppSettings:
    """Static settings used by DCMF."""

    application_name: str = "Drone Control Mapping Framework"
    organization_name: str = "Aviation Lab"
    version: str = "0.5.1"

    window_width: int = 1500
    window_height: int = 900

    log_directory: Path = Path("logs")
    experiment_directory: Path = Path("experiments")
    export_directory: Path = Path("exports")
    database_path: Path = Path("data") / "dcmf.sqlite3"
    iq_directory: Path = Path("data") / "iq"
    controller_mapping_path: Path = (
        Path("data") / "controller_mapping.json"
    )

    mavlink_baud: int = 57600

    sdr_center_frequency_hz: int = 915_000_000
    sdr_sample_rate_hz: int = 2_000_000
    sdr_gain_db: float = 30.0

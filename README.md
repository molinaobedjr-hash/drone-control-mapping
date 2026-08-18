# Drone Control Mapping Framework (DCMF)

DCMF is a PySide6 desktop recorder and offline analysis toolkit for mapping a
RadioMaster TX16S USB joystick to MAVLink control traffic, flight-controller
telemetry, and 915 MHz SDR IQ observations. SQLite is the structured source of
truth; large IQ files remain separate and are referenced by experiment ID.

The current application is DCMF 1.0.0. It includes experiment packaging,
automatic CSV/JSON exports, guided trials, session-quality review,
synchronized analysis, replay plots, guided-trial feature extraction, and a
Random Forest baseline. Optional MAVLink `MANUAL_CONTROL` output is disabled
by default and guarded for disarmed bench mapping only.

## Start here

```bash
cd /home/obd/drone-control-mapping
source .venv/bin/activate
python src/main.py
```

Before connecting hardware, read the [operator manual](docs/OPERATOR_MANUAL.md).
The [command reference](docs/COMMAND_REFERENCE.md) contains copy/paste commands
for setup, device detection, data inspection, testing, troubleshooting, and
analysis.

## Documentation

- [Operator manual](docs/OPERATOR_MANUAL.md)
- [Command reference](docs/COMMAND_REFERENCE.md)
- [QGroundControl setup and validation](docs/QGROUNDCONTROL.md)
- [Data, synchronized analysis, replay, and ML](docs/ANALYSIS_AND_ML.md)
- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Known hardware and validation record](docs/HARDWARE_VALIDATION.md)

## Quick verification

```bash
PYTHONPATH=src python -m dcmf.cli devices
PYTHONPATH=src python -m dcmf.cli list
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

## Important boundaries

- DCMF is an experimental mapping tool, not an autopilot or flight-safety
  system.
- Keep the vehicle disarmed and remove propellers or otherwise isolate
  propulsion during mapping.
- DCMF never sends arm, mode-change, or button commands. Its optional output is
  `MANUAL_CONTROL` only and is stopped on experiment stop or disconnect.
- QGroundControl and DCMF cannot directly open the same `/dev/ttyUSB*` serial
  port simultaneously. Finish QGroundControl setup, disconnect it, then use
  DCMF.
- Stream alignment is based on host monotonic timestamps. It is not hardware
  clock synchronization.
- A 2 MS/s USRP capture centered at 915 MHz observes only a slice of a
  frequency-hopping SiK/RFD-style radio link; it must not be described as a
  complete over-the-air capture.

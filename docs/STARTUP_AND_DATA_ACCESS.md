# Startup and Data Access

This former startup guide has been consolidated to remove outdated version and
receive-only instructions.

- Use the [DCMF 1.0 Operator Manual](OPERATOR_MANUAL.md) for the full workflow.
- Use the [Command Reference](COMMAND_REFERENCE.md) for every setup, device,
  data, analysis, SQLite, test, and troubleshooting command.
- Use the [QGroundControl Guide](QGROUNDCONTROL.md) for joystick calibration,
  Mode 2/RETA, `MANUAL_CONTROL`, channel verification, and serial-port handoff.

Quick start:

```bash
cd /home/obd/drone-control-mapping
source .venv/bin/activate
PYTHONPATH=src python -m dcmf.cli devices
python src/main.py
```

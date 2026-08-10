# DCMF Milestone 4 — RFD900 / MAVLink Receive-Only Acquisition

Milestone 4 adds:

- Linux serial-port discovery
- selectable serial port and baud rate
- Connect / Disconnect controls
- background pymavlink parser
- inbound MAVLink message display
- HEARTBEAT indication
- message count
- raw MAVLink frame bytes stored as hexadecimal
- decoded MAVLink fields stored as JSON
- unified DCMF timestamps
- SQLite storage in `mavlink_messages`

This milestone does not send vehicle commands.

## Install

```bash
source .venv/bin/activate
pip install -r requirements-m4.txt
python src/main.py
```

## Test tonight without telemetry hardware

The MAVLink panel should load and either list serial devices already attached
to the computer or display `No serial devices found`.

The application should continue to work normally if no telemetry modem exists.

## Hardware validation

When the telemetry modem is attached:

1. Click Refresh.
2. Select the `/dev/ttyUSB*` or `/dev/ttyACM*` device.
3. Start with 57600 baud unless the radio configuration says otherwise.
4. Click Connect.
5. A valid active MAVLink link should begin producing decoded message names.
6. HEARTBEAT will populate when a HEARTBEAT message is observed.

Do not have another program hold the same serial device while testing DCMF.
If QGroundControl is using the serial port, disconnect/close that connection
before DCMF opens it. A routing architecture can be added later if simultaneous
clients are required.

## Verify database after a recorded test

```bash
sqlite3 -header -column data/dcmf.sqlite3 \
"SELECT message_name, system_id, component_id, substr(raw_hex,1,50) AS raw FROM mavlink_messages LIMIT 20;"
```

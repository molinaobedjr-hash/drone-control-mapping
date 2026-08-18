# DCMF Command Reference

Run commands from `/home/obd/drone-control-mapping` unless a section says
otherwise. Commands using `python -m dcmf.cli` need `PYTHONPATH=src` because
this repository uses a `src/` layout and is not installed as a wheel.

## Repository and Python setup

```bash
cd /home/obd/drone-control-mapping
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

On Debian/Kali, these system tools may be installed with:

```bash
sudo apt update
sudo apt install python3-venv sqlite3 uhd-host
```

If `rx_samples_to_file` is not on `PATH`, DCMF also checks common UHD example
locations such as `/usr/libexec/uhd/examples/rx_samples_to_file`.

## Start and stop

```bash
cd /home/obd/drone-control-mapping
source .venv/bin/activate
python src/main.py
```

Stop from the GUI after ending the experiment. `Ctrl+C` is only for terminating
a terminal-side diagnostic command, not the preferred way to stop DCMF.

## One-command device report

```bash
PYTHONPATH=src python -m dcmf.cli devices
```

This reports pygame/SDL joysticks, serial devices, UHD executable status, and
discovered USRPs.

## TX16S and USB checks

```bash
lsusb
ls -l /dev/input/js* /dev/input/event* 2>/dev/null
python - <<'PY'
import pygame
pygame.init(); pygame.joystick.init()
print("joysticks:", pygame.joystick.get_count())
for i in range(pygame.joystick.get_count()):
    j = pygame.joystick.Joystick(i); j.init()
    print(i, j.get_name(), "axes", j.get_numaxes(), "buttons", j.get_numbuttons())
pygame.quit()
PY
```

View the saved DCMF axis mapping:

```bash
python -m json.tool data/controller_mapping.json
```

## Telemetry-radio serial checks

```bash
python -m serial.tools.list_ports -v
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
udevadm info --query=property --name=/dev/ttyUSB0
groups
sudo fuser -v /dev/ttyUSB0
```

Add serial-port permission, then log out and back in:

```bash
sudo usermod -aG dialout "$USER"
```

`Errno 16` means the device is busy. Close QGroundControl, Mission Planner,
serial terminals, and other processes shown by `fuser`. Do not run two direct
serial owners at once.

To watch raw serial bytes temporarily, use a serial tool only while DCMF and
QGroundControl are disconnected. Do not send unknown AT commands to a radio or
unknown MAVLink commands to a vehicle.

## USRP/UHD checks

```bash
command -v uhd_find_devices
command -v uhd_usrp_probe
command -v rx_samples_to_file
find /usr/libexec/uhd /usr/lib/uhd /usr/local/libexec/uhd -name rx_samples_to_file -type f 2>/dev/null
uhd_find_devices
uhd_usrp_probe
```

List current IQ files and sizes:

```bash
find data/iq -type f -name '*.sc16' -printf '%TY-%Tm-%Td %TH:%TM  %12s  %p\n' | sort
du -sh data/iq
du -h data/iq/* 2>/dev/null
```

Inspect one sc16 file without changing it:

```bash
stat data/iq/EXPERIMENT-ID/FILE.sc16
python - <<'PY'
from pathlib import Path
import numpy as np
p = Path("data/iq/EXPERIMENT-ID/FILE.sc16")
x = np.fromfile(p, dtype="<i2", count=20)
print("first 10 I/Q pairs:", x.reshape(-1, 2))
print("bytes:", p.stat().st_size, "complex samples:", p.stat().st_size // 4)
PY
```

sc16 is binary interleaved little-endian signed 16-bit I,Q. It is not a text
file.

## Application log

```bash
tail -n 100 logs/dcmf.log
tail -f logs/dcmf.log
grep -iE 'error|exception|failed|permission|busy' logs/dcmf.log | tail -n 100
```

Press `Ctrl+C` to stop `tail -f`.

## DCMF experiment commands

List completed experiments:

```bash
PYTHONPATH=src python -m dcmf.cli list
```

Include incomplete/recording rows or return JSON:

```bash
PYTHONPATH=src python -m dcmf.cli list --all
PYTHONPATH=src python -m dcmf.cli list --json
```

Show one experiment by exact/partial UUID or name:

```bash
PYTHONPATH=src python -m dcmf.cli show "milestone_8_retest"
PYTHONPATH=src python -m dcmf.cli show df3a4326
```

Show manual and guided markers:

```bash
PYTHONPATH=src python -m dcmf.cli markers "EXPERIMENT NAME"
```

Show the newest saved MAVLink frames, including raw hex:

```bash
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT NAME" --limit 25
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT NAME" --message MANUAL_CONTROL --limit 100
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT NAME" --message RC_CHANNELS --limit 100
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT NAME" --message SERVO_OUTPUT_RAW --limit 100
```

Run quality checks and optionally save readable JSON:

```bash
PYTHONPATH=src python -m dcmf.cli quality "EXPERIMENT NAME"
PYTHONPATH=src python -m dcmf.cli quality "EXPERIMENT NAME" --output analysis/quality.json
```

Write synchronized analysis files:

```bash
PYTHONPATH=src python -m dcmf.cli analyze "EXPERIMENT NAME"
PYTHONPATH=src python -m dcmf.cli analyze "EXPERIMENT NAME" --output analysis --tolerance-ms 250
```

Build features from every completed session:

```bash
PYTHONPATH=src python -m dcmf.cli features --output analysis/ml
```

Build features from selected sessions, or skip reading IQ for a fast run:

```bash
PYTHONPATH=src python -m dcmf.cli features --experiment "run 1" --experiment "run 2" --output analysis/ml
PYTHONPATH=src python -m dcmf.cli features --skip-iq --output analysis/ml-fast
```

Train and evaluate the Random Forest baseline:

```bash
PYTHONPATH=src python -m dcmf.cli train analysis/ml/guided_trial_features.csv --output analysis/model
```

Show CLI help:

```bash
PYTHONPATH=src python -m dcmf.cli --help
PYTHONPATH=src python -m dcmf.cli analyze --help
PYTHONPATH=src python -m dcmf.cli features --help
```

## SQLite interactive use

Do not open `data/dcmf.sqlite3` in the text editor. Open it with:

```bash
sqlite3 -readonly data/dcmf.sqlite3
```

At the `sqlite>` prompt:

```sql
.headers on
.mode column
.tables
.schema experiments
.schema mavlink_messages
SELECT id, name, operator, status,
       datetime(started_utc_ns / 1000000000, 'unixepoch') AS started_utc
FROM experiments
ORDER BY started_utc_ns DESC;
.quit
```

The correct column is `started_utc_ns`, not `started_uts_ns`.

Select one experiment by name:

```sql
SELECT *
FROM experiments
WHERE name = 'Untitled Experiment'
ORDER BY started_utc_ns DESC;
```

Set a reusable experiment ID during the interactive session:

```sql
.parameter init
.parameter set @experiment_id 'PASTE-UUID-HERE'
```

Count every source:

```sql
SELECT
  (SELECT COUNT(*) FROM controller_samples WHERE experiment_id=@experiment_id) AS controller,
  (SELECT COUNT(*) FROM mavlink_messages WHERE experiment_id=@experiment_id) AS mavlink,
  (SELECT COUNT(*) FROM sdr_records WHERE experiment_id=@experiment_id) AS sdr,
  (SELECT COUNT(*) FROM events WHERE experiment_id=@experiment_id) AS events;
```

Count MAVLink messages by direction and type:

```sql
SELECT direction, message_name, COUNT(*) AS messages
FROM mavlink_messages
WHERE experiment_id=@experiment_id
GROUP BY direction, message_name
ORDER BY direction, messages DESC;
```

Check control-path records and raw hex:

```sql
SELECT direction, message_name, COUNT(*) AS messages,
       SUM(CASE WHEN raw_hex IS NULL OR trim(raw_hex)='' THEN 1 ELSE 0 END) AS missing_hex
FROM mavlink_messages
WHERE experiment_id=@experiment_id
  AND message_name IN ('MANUAL_CONTROL','RC_CHANNELS','RC_CHANNELS_RAW','SERVO_OUTPUT_RAW')
GROUP BY direction, message_name;
```

View markers and guided intervals:

```sql
SELECT monotonic_ns, kind,
       json_extract(payload_json, '$.label') AS label,
       json_extract(payload_json, '$.action') AS action,
       json_extract(payload_json, '$.trial_number') AS trial
FROM events
WHERE experiment_id=@experiment_id
  AND source='OPERATOR'
ORDER BY monotonic_ns;
```

View mapped controller values:

```sql
SELECT monotonic_ns,
       json_extract(payload_json, '$.mapped.roll') AS roll,
       json_extract(payload_json, '$.mapped.pitch') AS pitch,
       json_extract(payload_json, '$.mapped.yaw') AS yaw,
       json_extract(payload_json, '$.mapped.throttle') AS throttle
FROM events
WHERE experiment_id=@experiment_id
  AND source='CONTROLLER' AND kind='SAMPLE'
ORDER BY monotonic_ns
LIMIT 50;
```

View saved raw MAVLink hex and decoded JSON:

```sql
.mode line
SELECT monotonic_ns, direction, message_name, raw_hex, decoded_json
FROM mavlink_messages
WHERE experiment_id=@experiment_id
ORDER BY monotonic_ns
LIMIT 25;
```

## One-line SQLite queries from the normal shell

```bash
sqlite3 -readonly -header -column data/dcmf.sqlite3 \
"SELECT id,name,status FROM experiments ORDER BY started_utc_ns DESC;"

sqlite3 -readonly -header -column data/dcmf.sqlite3 \
"SELECT direction,message_name,COUNT(*) AS n FROM mavlink_messages WHERE experiment_id='PASTE-UUID' GROUP BY direction,message_name ORDER BY n DESC;"

sqlite3 -readonly -header -column data/dcmf.sqlite3 \
"SELECT kind,json_extract(payload_json,'$.label') AS label FROM events WHERE experiment_id='PASTE-UUID' AND source='OPERATOR' ORDER BY monotonic_ns;"
```

## Exports and package files

```bash
find experiments -maxdepth 2 -type f -printf '%p\n' | sort
find exports -maxdepth 2 -type f -printf '%p\n' | sort
find analysis -maxdepth 3 -type f -printf '%p\n' | sort
python -m json.tool exports/SESSION/experiment_summary.json
python -m json.tool experiments/SESSION/session_info.json
head -n 20 exports/SESSION/events.csv
head -n 5 exports/SESSION/mavlink_messages.csv
```

CSV files contain commas inside quoted JSON fields, so `column -s,` is not a
reliable CSV parser. Use pandas when selecting columns:

```bash
python - <<'PY'
import pandas as pd
p = "exports/SESSION/mavlink_messages.csv"
df = pd.read_csv(p)
print(df[["direction", "message_name", "raw_hex"]].head(20).to_string(index=False))
PY
```

## Tests and source verification

```bash
PYTHONPATH=src python -m compileall -q src
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
git status --short --branch
git diff --stat
git diff -- src tests docs README.md
```

## Database integrity and backup

Close DCMF before a maintenance check or backup:

```bash
sqlite3 data/dcmf.sqlite3 "PRAGMA quick_check;"
mkdir -p backups
sqlite3 data/dcmf.sqlite3 ".backup 'backups/dcmf-backup.sqlite3'"
sqlite3 -readonly backups/dcmf-backup.sqlite3 "PRAGMA integrity_check;"
```

Do not delete `data/dcmf.sqlite3-wal` or `data/dcmf.sqlite3-shm` while DCMF is
running. Do not edit or truncate IQ, SQLite, package, or export files to make a
quality report pass.

# DCMF 1.0 Operator Manual

This is the primary operating manual for the Drone Control Mapping Framework.
It covers a complete bench experiment from cable setup through review and
analysis. The abbreviated startup files in this directory point back here.

## 1. What DCMF records

During an active experiment DCMF records these streams with experiment IDs,
host monotonic timestamps, and UTC timestamps:

- raw TX16S USB axes, buttons, hats, and mapped roll/pitch/yaw/throttle;
- every received MAVLink message, decoded JSON, direction, and raw frame hex;
- every DCMF-transmitted `MANUAL_CONTROL` frame and its raw frame hex;
- returned `RC_CHANNELS`/`RC_CHANNELS_RAW` when supplied by the flight
  controller;
- `SERVO_OUTPUT_RAW` and all other received MAVLink telemetry;
- USRP capture start/stop metadata and the associated sc16 IQ filename;
- manual markers and guided action start/end markers.

SQLite at `data/dcmf.sqlite3` is the structured source of truth. IQ is kept in
`data/iq/<experiment-id>/` because it is too large for SQLite. Completed
sessions also receive package and export folders.

## 2. Safety boundary

DCMF is for mapping on a bench, not flying. Before control-path work:

1. Remove propellers, disconnect propulsion power, or otherwise make motor
   motion physically harmless.
2. Keep the flight controller disarmed.
3. Secure the airframe and keep people clear of motors.
4. Do not enable DCMF control output merely to test whether the link exists;
   first confirm heartbeat and device identities.

DCMF sends no arm command, mode change, or joystick buttons. Optional output is
only MAVLink `MANUAL_CONTROL`. It is opt-in, requires an active experiment and
complete DCMF mapping, stops on a controller/radio/experiment disconnect, and
is suppressed when a received vehicle heartbeat reports ARMED. These are
software guards, not a substitute for physical safety.

## 3. Hardware connection layout

The validated intended path is:

```text
TX16S --USB joystick--> DCMF laptop
                         |
                         +--MANUAL_CONTROL--> ground 915 MHz telemetry radio
                                                )) radio link ((
                                           airborne telemetry radio
                                                |
                                           CubeOrange+ TELEM port

CubeOrange+ telemetry --same link--> DCMF laptop

USRP antenna --receive-only RF observation near 915 MHz--> IQ file
```

The photographed ground modem is an mRo 915 MHz SiK-style USB telemetry radio;
project notes may call the link RFD900. DCMF intentionally labels it
generically as a 915 MHz telemetry radio because MAVLink processing does not
depend on the exact modem enclosure. The airborne modem model is not proven by
the photographs.

The USRP is not inline and does not forward traffic. It listens to RF energy
near its configured center frequency.

## 4. First-time computer setup

From the repository root:

```bash
cd /home/obd/drone-control-mapping
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

UHD command-line tools and SQLite must also exist. See
[COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) for detection and Debian/Kali
package commands.

If the telemetry serial port reports permission denied, add the login user to
`dialout`, then log out and back in:

```bash
sudo usermod -aG dialout "$USER"
```

Do not use repeated `sudo` launches of DCMF as a serial-permission workaround.

## 5. Device checks before every session

Connect the TX16S in USB Joystick/HID mode, the ground telemetry radio, and the
USRP. Then run:

```bash
cd /home/obd/drone-control-mapping
source .venv/bin/activate
PYTHONPATH=src python -m dcmf.cli devices
```

The output should show:

- a joystick named similar to `OpenTX RM TX16S Joystick`, with axes/buttons;
- a serial device such as `/dev/ttyUSB0`, often described as `FT230X Basic
  UART [SiK Radio]`;
- a ready UHD backend and the expected USRP serial/product.

Useful independent checks are:

```bash
lsusb
python -m serial.tools.list_ports -v
uhd_find_devices
uhd_usrp_probe
```

If `/dev/ttyUSB0` is busy (`Errno 16`), close QGroundControl and any serial
terminal, then identify the owner:

```bash
sudo fuser -v /dev/ttyUSB0
```

Only one application may directly own this serial port at a time.

## 6. QGroundControl preparation

Use QGroundControl before DCMF for controller calibration, flight-controller
parameter inspection, and control-path validation. Do not leave QGroundControl
connected to the telemetry serial port while DCMF tries to open it.

The project-validated settings are:

- TX16S USB joystick selected and enabled;
- QGroundControl Mode 2;
- EdgeTX model channel order RETA;
- QGroundControl sends joystick input using `MANUAL_CONTROL`;
- roll maps to RC channel 1;
- pitch maps to RC channel 2;
- throttle maps to RC channel 3;
- yaw maps to RC channel 4.

QGroundControl's Mode 1/2/3/4 describes physical stick layout. EdgeTX's RETA
describes channel order. They are related configuration choices but are not
the same notation.

Move each stick separately in QGroundControl and verify the Radio page's raw
channels. Disabling the QGroundControl joystick should stop the channel
changes; re-enabling it should restore them. Save a parameter backup. Then
disconnect/close QGroundControl so DCMF can own the ground-radio serial port.

Full instructions and troubleshooting are in [QGROUNDCONTROL.md](QGROUNDCONTROL.md).

## 7. Start DCMF

```bash
cd /home/obd/drone-control-mapping
source .venv/bin/activate
python src/main.py
```

In the application:

1. Confirm the TX16S panel says Connected and its raw axes move.
2. If needed, choose **Tools → Calibrate TX16S**. Capture a neutral baseline,
   learn roll/pitch/yaw/throttle one at a time, move each requested control
   through both directions/full travel, and save only when all four mappings
   are present.
3. Compare DCMF's mapped bars with QGroundControl's previously verified axes:
   roll must cause roll, pitch pitch, yaw yaw, and throttle throttle. Fix an
   inverted or wrong axis before recording.
4. In the telemetry panel select the actual radio serial device and 57600 baud,
   then click **Connect**.
5. Wait for a vehicle heartbeat. Confirm the displayed system/component and
   DISARMED state.
6. In the SDR panel select the expected USRP and confirm center frequency,
   sample rate, and gain. The validated default is 915 MHz, 2 MS/s, 30 dB,
   sc16. Enable automatic capture if IQ is required.

The manual Start/Stop IQ buttons are useful for diagnostics, but normal
experiments should use automatic capture so experiment and IQ lifecycle stay
together.

## 8. Run a guided mapping experiment

1. Enter a descriptive experiment name, operator, and notes. Include hardware
   changes, radio settings, test conditions, and any missing source.
2. Click **Start Experiment**. This starts SQLite recording and, when enabled,
   automatic IQ capture.
3. If this test is intended to exercise the laptop-to-aircraft command path,
   check **Transmit mapped MANUAL_CONTROL (disarmed tests only)** after the
   experiment starts. Leave it unchecked for passive telemetry/IQ collection.
4. Select a guided action and target repetitions. For each repetition:
   click **Start Guided Trial**, move only the named control in the named
   direction, hold briefly if useful, return it, then click **End Guided
   Trial**.
5. Complete all eight actions: roll right/left, pitch forward/back, yaw
   right/left, and throttle up/down. Three repeats each gives 24 trials.
6. Use **Mark Event** for abnormalities or context. The label is editable for
   each marker; it is not a one-time permanent label.
7. Click **Stop Experiment**. DCMF first disables command output and stops IQ,
   then commits SQLite and generates exports. Wait for the saved/exported
   status message before closing.

Do not overlap guided trials. Keep unrelated axes neutral and perform one clear
motion per interval. Consistency matters more than speed.

## 9. Immediate post-run checks

Use **Experiment → Review Completed Sessions**. A strong session should show:

- complete lifecycle;
- controller samples;
- MAVLink messages and heartbeat;
- raw hex present for every MAVLink record;
- matched SDR start/stop and an existing non-empty IQ file;
- package and export files;
- complete guided intervals and expected action coverage;
- a complete controller-mapping snapshot;
- timestamps inside experiment bounds.

For a command-path run, additionally confirm nonzero counts for TX
`MANUAL_CONTROL`, RX `RC_CHANNELS`, and RX `SERVO_OUTPUT_RAW`. A heartbeat alone
only proves telemetry connectivity; it does not prove control commands were
accepted.

From the terminal:

```bash
PYTHONPATH=src python -m dcmf.cli list
PYTHONPATH=src python -m dcmf.cli show "EXPERIMENT NAME"
PYTHONPATH=src python -m dcmf.cli markers "EXPERIMENT NAME"
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT NAME" --message MANUAL_CONTROL
PYTHONPATH=src python -m dcmf.cli quality "EXPERIMENT NAME"
```

## 10. View and analyze data

Never open `dcmf.sqlite3` as text; the unreadable characters are normal binary
SQLite pages. Use the GUI review/replay windows, the DCMF CLI, SQLite, or the
automatic CSV/JSON exports.

Choose **Experiment → Analyze / Replay Sessions** to plot input,
`MANUAL_CONTROL`, returned RC channels, and servo outputs. The time slider and
Play button require no hardware. **Write Analysis Files** creates a synchronized
CSV and JSON summary. **Build ML Dataset** creates one feature row per complete
guided trial. **Train Baseline** evaluates and saves a Random Forest model.

Equivalent commands are:

```bash
PYTHONPATH=src python -m dcmf.cli analyze "EXPERIMENT NAME"
PYTHONPATH=src python -m dcmf.cli features --output analysis/ml
PYTHONPATH=src python -m dcmf.cli train analysis/ml/guided_trial_features.csv --output analysis/model
```

Read [ANALYSIS_AND_ML.md](ANALYSIS_AND_ML.md) before interpreting correlation,
SDR power, or classification results.

## 11. Where files are stored

```text
data/dcmf.sqlite3                 primary structured database
data/dcmf.sqlite3-wal             live SQLite write-ahead log
data/dcmf.sqlite3-shm             live SQLite shared-memory file
data/controller_mapping.json      DCMF USB-axis mapping
data/iq/<experiment-id>/*.sc16    raw interleaved int16 I/Q
experiments/<session>/             metadata/config snapshots and IQ reference
exports/<session>/                 per-table CSVs and experiment_summary.json
analysis/<session>/                synchronized CSV and analysis summary
analysis/ml/...                    feature datasets and model artifacts
logs/dcmf.log                      application log
```

The `-wal` and `-shm` files are part of a live SQLite database and are not
separate experiments. Do not delete them while DCMF is running. The package
`iq` entry is normally a symbolic link/reference to `data/iq`; it is not a
second copy of the large capture.

## 12. Shutdown and recovery

Normal shutdown is: end the active guided trial, stop the experiment, wait for
export completion, disconnect hardware if desired, then close DCMF.

If DCMF closed during a recording, it attempts to close the session and export
after the database writer commits. Inspect the log and session-quality report.
Do not edit SQLite manually to make a failed check disappear; preserve the raw
record and document what happened.

To make a consistent SQLite backup after DCMF is closed:

```bash
mkdir -p backups
sqlite3 data/dcmf.sqlite3 ".backup 'backups/dcmf-backup.sqlite3'"
```

For every other operational or diagnostic command, see
[COMMAND_REFERENCE.md](COMMAND_REFERENCE.md).

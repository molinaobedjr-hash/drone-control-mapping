# DCMF Data, Analysis, Replay, and Machine Learning

This document explains what the generated files mean and what conclusions they
can support. All offline tools are read-only with respect to SQLite and IQ.

## Data hierarchy

SQLite `data/dcmf.sqlite3` is authoritative for structured records. The main
tables are:

| Table | Contents |
|---|---|
| `experiments` | name, operator, notes, lifecycle, start/end clocks |
| `events` | every EventBus event, including mapped controller samples and labels |
| `controller_samples` | raw axes/buttons/hats |
| `mavlink_messages` | direction, message identity, raw hex, decoded JSON |
| `sdr_records` | IQ lifecycle/configuration/file references |

Raw sc16 files live under `data/iq/<experiment-id>/`. Per-session files in
`experiments/` snapshot configuration and provenance. Per-session `exports/`
contain filtered CSV/JSON for convenient inspection. `analysis/` is derived
and can be regenerated from SQLite plus IQ.

## Which value belongs to which layer

| Layer | DCMF representation | Meaning |
|---|---|---|
| Physical operator input | mapped controller roll/pitch/yaw/throttle | USB HID axes after DCMF calibration |
| Laptop command | TX `MANUAL_CONTROL` x/y/z/r | bytes DCMF sent to the telemetry serial connection |
| Flight-controller input state | RX `RC_CHANNELS` or `RC_CHANNELS_RAW` | RC values the flight controller reports, when available |
| Flight-controller output | RX `SERVO_OUTPUT_RAW` | output PWM commands reported by the controller |
| Over-the-air observation | USRP sc16 IQ | RF samples near the configured center frequency |
| Protocol evidence | `raw_hex` | complete MAVLink frame bytes for that decoded record |

The raw MAVLink hex belongs to the serial MAVLink protocol, not to raw RF IQ.
The USRP file contains I/Q sample pairs and is not decoded MAVLink hex.

## Host-time synchronization

Controller, MAVLink, SDR metadata, and labels receive timestamps from the same
host process. `monotonic_ns` is used for ordering and elapsed time; `utc_ns` is
for human dates and cross-file provenance.

This avoids wall-clock jumps but does not remove USB polling, serial buffering,
radio transport, flight-controller scheduling, UHD process startup, or OS
latency. DCMF therefore calls this software/host synchronization and retains
the nearest-match delta in milliseconds. It never claims hardware clock
synchronization.

## Synchronized analysis

From the GUI choose **Experiment → Analyze / Replay Sessions → Write Analysis
Files**, or run:

```bash
PYTHONPATH=src python -m dcmf.cli analyze "EXPERIMENT NAME"
```

Outputs under `analysis/<name>_<id>/`:

- `synchronized_samples.csv`: one row per mapped controller sample with the
  nearest `MANUAL_CONTROL`, RC channel, and servo-output values;
- `analysis_summary.json`: counts, alignment-delta summaries, descriptive
  correlations, assumptions, and limitations.

Default matching tolerance is 250 ms. A matched row retains
`manual_delta_ms`, `rc_delta_ms`, and `servo_delta_ms`; positive means that
stream's record occurred after the controller sample. Tight analysis should
filter by an application-appropriate absolute delta.

RC normalization uses the project-validated channel assignment roll=1,
pitch=2, throttle=3, yaw=4. Zero/unavailable PWM fields become missing values,
not extreme controls.

## Replay

The replay window loads completed data directly from SQLite and requires no
hardware. It plots:

- mapped TX16S controls;
- TX `MANUAL_CONTROL` when present (otherwise any recorded direction);
- returned channels 1–4;
- `SERVO_OUTPUT_RAW` outputs 1–8;
- guided trial start/end boundaries.

Play/pause, speed, and the time slider move a shared cursor. Replay is a view
of recorded host timestamps; it does not transmit anything and cannot control
hardware.

## Guided-trial feature dataset

Build through the replay window or CLI:

```bash
PYTHONPATH=src python -m dcmf.cli features --output analysis/ml
```

`guided_trial_features.csv` contains one row per complete action interval.
Features include:

- duration, counts, and observed rates;
- mean, standard deviation, min, max, range, mean/peak absolute value, and
  endpoint delta for each mapped input;
- the same aggregates for `MANUAL_CONTROL` and normalized RC values;
- raw returned RC channels 1–4;
- servo outputs 1–16;
- bounded sc16 mean and peak power estimates when the IQ file is available.

`feature_metadata.json` records source experiments, feature names, errors,
label/group columns, and synchronization assumptions. Use `--skip-iq` for a
fast dataset that does not read IQ.

IQ power uses the `CAPTURE_START` event as approximate sample zero and reads at
most 250,000 complex samples per trial. Process startup and buffering mean this
window is approximate. It is a useful feature, not a precisely synchronized RF
measurement.

## Random Forest baseline

```bash
PYTHONPATH=src python -m dcmf.cli train \
  analysis/ml/guided_trial_features.csv \
  --output analysis/model
```

Outputs include:

- `random_forest.joblib` full preprocessing/model pipeline;
- `metrics.json` evaluation method, metrics, report, and limitations;
- `predictions.csv` held-out/cross-validated predictions;
- `confusion_matrix.csv` and `confusion_matrix.png`;
- `feature_importance.csv`.

Identifiers, timestamps, action label, trial number, and automatic-end flag are
excluded from model features. Missing numeric values are median-imputed. The
seed is fixed for repeatability.

When at least two experiment IDs exist, evaluation holds out whole experiment
groups. This is preferable because neighboring trials from the same recording
share setup and noise. With only one experiment, stratified cross-validation
is used only if every class has at least two trials, and `metrics.json` warns
that generalization may be overstated. If data are insufficient, the command
returns a clear `insufficient_data` result instead of inventing a score.

For the intended eight-action classifier, collect all eight actions with at
least three repetitions per session and repeat across several independently
started experiments. Do not interpret a model trained on one action, one
session, or missing command/RC streams as evidence that the whole control path
has been mapped.

## SDR/FHSS limitation

SiK/RFD-style telemetry radios can frequency hop across a configured range.
The validated USRP configuration is centered at 915 MHz with a 2 MS/s sample
rate, so it observes roughly a 2 MHz slice at a time, not necessarily the full
hop range. Record radio `MIN_FREQ`, `MAX_FREQ`, `NUM_CHANNELS`, `AIR_SPEED`, and
related settings before making OTA claims. A missing burst may mean the radio
hopped outside the observed band rather than no command being transmitted.

Useful background:

- [SiK advanced configuration and FHSS](https://ardupilot.ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html)
- [mRo SiK telemetry radio documentation](https://docs.mrobotics.io/telemetry/sik-telemetry-radio-v2)
- [RFD modem product documentation](https://rfdesign.com.au/modems/)

## Interpretation checklist

Before claiming that a control is mapped, verify all applicable evidence:

1. The correct DCMF mapped input changes inside the correct guided interval.
2. TX `MANUAL_CONTROL` changes in the expected x/y/z/r field.
3. Raw hex is nonempty for the saved TX frame.
4. Returned RC channels are nonzero and the expected channel changes.
5. Servo/actuator telemetry changes only if the disarmed vehicle/firmware is
   expected to expose such a response.
6. SDR energy is treated as supporting RF evidence, not proof that one
   particular MAVLink frame caused one burst.
7. Match deltas and data rates are plausible.
8. Results repeat across trials and independent sessions.

Correlation alone is not causation. In a multi-axis system, scripted
single-axis guided trials, preserved protocol bytes, and repeatability provide
the strongest mapping evidence.

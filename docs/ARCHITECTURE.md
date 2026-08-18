# DCMF 1.0 Architecture

## Entry point and GUI

`src/main.py` calls `dcmf.app.run()`. The bootstrap loads `AppSettings`, sets up
logging, creates the Qt application, and opens `dcmf.gui.main_window.MainWindow`.

The integrated main window contains:

- experiment metadata/start/stop/marker controls;
- guided action/repetition controls;
- live TX16S raw and mapped controls;
- telemetry-radio port, heartbeat, decoded stream, vehicle state, and guarded
  `MANUAL_CONTROL` opt-in;
- USRP discovery/configuration/capture controls;
- synchronized event timeline and dataset counts;
- completed-session quality review;
- offline analysis/replay/feature/model workflow.

## Runtime flow

```text
ControllerReader QThread ---- ControllerSample ----+
                                                   |
MavlinkReader QThread ------- RX/TX packet --------+--> MainWindow
       ^                                           |       |
       +---- latest mapped controls (thread-safe) -+       v
                                                   EventBus
SdrCaptureWorker QThread ---- lifecycle -----------+   /         \
                                                       GUI       DatabaseWriter
Operator/Guided UI ----------- markers ------------+             background thread
                                                                  |
                                                                  v
                                                               SQLite WAL
```

Acquisition never performs SQLite writes directly. Each source emits data to
the GUI thread. `EventBus.publish()` adds one host `perf_counter_ns` monotonic
timestamp and one `time_ns` UTC timestamp. The GUI displays the event and the
asynchronous `DatabaseWriter` queues it into SQLite.

## Controller acquisition

`dcmf.acquisition.controller.reader.ControllerReader` uses pygame/SDL to
discover and poll the first USB joystick at 50 Hz. It reports all raw axes,
buttons, and hats. `ControllerMapping` converts four selected raw axes to
normalized roll, pitch, yaw, and throttle without deleting raw values.

The mapping is stored at `data/controller_mapping.json` and snapshotted into
every experiment package. Missing/invalid mapping files safely load as an
unmapped controller.

## MAVLink transport

`dcmf.acquisition.mavlink.reader.MavlinkReader` is the only owner of the serial
connection. It parses all inbound pymavlink messages and preserves decoded JSON
plus exact `get_msgbuf()` bytes as spaced hexadecimal.

Optional output is disabled by default. When explicitly enabled, the worker:

- requires a recently supplied complete mapped sample;
- targets the system ID learned from a non-GCS autopilot heartbeat;
- sends a GCS heartbeat at 1 Hz and `MANUAL_CONTROL` at 20 Hz;
- maps pitch→x, roll→y, throttle→z, yaw→r;
- sets buttons to zero;
- emits each generated frame back through the same packet/EventBus/database
  path with direction `TX` and raw hex;
- suppresses commands while the vehicle reports ARMED.

The GUI additionally requires a connected controller, live telemetry worker,
observed vehicle heartbeat, complete mapping, and active experiment. It
disables output on experiment stop, serial disconnect, controller disconnect,
armed heartbeat, or application close.

## SDR acquisition

`dcmf.acquisition.sdr.reader` locates `uhd_find_devices` and
`rx_samples_to_file`, including common Debian/Kali UHD example paths. A worker
launches the UHD process in a separate process group, records capture
configuration/lifecycle, and performs a clean SIGINT stop before experiment
finalization.

Raw sc16 is written directly to `data/iq/<experiment-id>/`; it is not passed
through Qt or SQLite. SQLite stores configuration, lifecycle timestamps,
filename, size, and return code. This avoids blocking the GUI/database with an
8 MB/s default IQ stream.

## Experiment lifecycle

Start:

1. `DatabaseWriter.start_experiment()` allocates a UUID and queues the row.
2. `create_experiment_package()` writes metadata, runtime/configuration,
   controller mapping, synchronization declaration, and IQ reference.
3. The guided-trial tracker resets.
4. An `EXPERIMENT START` event is published.
5. Automatic IQ capture starts when enabled and a USRP is selected.

Stop:

1. Guarded MAVLink output is disabled and logged.
2. Any active guided interval closes automatically and is marked as such.
3. IQ capture stops first so its stop record/file size enter the session.
4. `EXPERIMENT STOP` is published.
5. SQLite marks the experiment complete and commits.
6. Only after the commit, the export worker writes filtered per-session CSVs
   and `experiment_summary.json` and finalizes package metadata.

SQLite remains primary even if package/export generation fails.

## Offline analysis flow

```text
SQLite + IQ reference
        |
        v
load_session() -- decoded pandas frames + guided intervals
        |
        +--> synchronize_session() --> synchronized_samples.csv + summary
        |
        +--> ReplaySession/Qt plots (read-only)
        |
        +--> trial feature extraction --> guided_trial_features.csv
                                          |
                                          v
                                 Random Forest evaluation/artifacts
```

Offline readers open SQLite with URI `mode=ro`. They do not modify the database
or IQ. Derived outputs go under `analysis/`.

## Database invariants

- Every structured row belongs to an experiment UUID.
- Raw source fields are preserved; normalized/decoded/derived values are
  additional fields.
- `direction` distinguishes MAVLink RX from DCMF-generated TX.
- Raw MAVLink hex and decoded JSON are saved together.
- Timeline ordering uses monotonic nanoseconds.
- UTC nanoseconds remain available for human time/provenance.
- IQ is referenced, not copied into SQLite or duplicated per export.
- Automatic exports contain only the selected experiment.

## Synchronization statement

DCMF timestamps an event when host software receives/emits it. Controller USB,
serial, radio, flight-controller, subprocess, and UHD buffers introduce
latency. `process_launch_monotonic_ns` can differ from the later Qt
`CAPTURE_START` event. There is no PPS, GPS-disciplined common clock, or
flight-controller clock conversion in DCMF 1.0. Any report must call this
shared host timestamp alignment, not hardware synchronization.

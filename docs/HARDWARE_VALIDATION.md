# Known Hardware and Validation Record

This file records what has been observed, what has been functionally verified,
and what remains a per-session check. It is not a substitute for the aircraft
manufacturer's documentation.

## Identified hardware

- RadioMaster TX16S exposed as an OpenTX/EdgeTX USB joystick.
- CubePilot CubeOrange+ flight controller module.
- CubePilot/uAvionix ADS-B IN carrier board visible in photographs.
- Ground USB modem marked `mRo 915 MHz`, enumerating as an FT230X Basic UART
  and identified by QGroundControl as a SiK radio.
- Airborne telemetry modem physically connected to a flight-controller
  telemetry port; its exact model is obscured/not proven by the supplied
  photographs.
- USRP discovered through UHD and validated for sc16 capture.
- Aurelia X6 airframe context supplied by the project owner.

Project documentation has referred to the telemetry link as RFD900. Software
and reports should use “915 MHz telemetry radio / SiK-RFD-style link” unless a
readable airborne label or saved modem configuration proves the exact pair.

## Previously observed firmware/configuration

- CubeOrangePlus / ArduCopter 4.5.4 (`505220da`) was observed in a QGC log.
- Vehicle system/component was 1/1; GCS system ID was 255.
- Telemetry serial speed was 57600 baud.
- `RCMAP_ROLL=1`, `RCMAP_PITCH=2`, `RCMAP_THROTTLE=3`, `RCMAP_YAW=4`.
- `RC_OVERRIDE_TIME=3`, `FS_GCS_ENABLE=1`, `FS_GCS_TIMEOUT=5` were observed.

These values are historical evidence, not guaranteed current state. Save and
review parameters again after firmware, hardware, or configuration changes.

## Verified behavior

- TX16S USB axes are acquired and saved by DCMF.
- DCMF controller calibration can map all four primary controls.
- QGC Mode 2 and EdgeTX RETA produce the verified RC mapping:
  roll 1, pitch 2, throttle 3, yaw 4.
- With QGC joystick enabled and sending `MANUAL_CONTROL`, the Radio page's
  channels move; disabling the joystick stops movement; re-enabling restores
  it.
- The ground/air telemetry path delivers vehicle heartbeat and other MAVLink
  telemetry.
- USRP produces a non-empty sc16 IQ file under the experiment UUID.
- SQLite records controller, MAVLink, SDR, markers, guided intervals, and raw
  MAVLink hex.
- Experiment packaging, automatic exports, guided-trial review, synchronized
  analysis, replay, feature generation, and baseline training have software
  tests.

## Final validation for the new DCMF output path

The DCMF 1.0 transmitter must receive one short disarmed bench validation on
the actual hardware:

1. Physically isolate propulsion and confirm DISARMED.
2. Close QGC so DCMF can own the telemetry serial port.
3. Connect TX16S, telemetry radio, and USRP.
4. Start a named experiment.
5. Enable guarded `MANUAL_CONTROL` output.
6. Run one short guided interval per axis, one axis at a time.
7. Stop normally and review the session.
8. Confirm TX `MANUAL_CONTROL` count is nonzero and raw hex is present.
9. Confirm x responds to pitch, y to roll, z to throttle, r to yaw.
10. Confirm returned `RC_CHANNELS` values are nonzero and RC1/2/3/4 match.
11. Inspect `SERVO_OUTPUT_RAW`; document whether disarmed firmware changes or
    suppresses those outputs.
12. Confirm the IQ file exists and record modem hop parameters before making
    RF coverage claims.

Useful commands:

```bash
PYTHONPATH=src python -m dcmf.cli quality "FINAL VALIDATION"
PYTHONPATH=src python -m dcmf.cli show "FINAL VALIDATION"
PYTHONPATH=src python -m dcmf.cli hex "FINAL VALIDATION" --message MANUAL_CONTROL --limit 100
PYTHONPATH=src python -m dcmf.cli hex "FINAL VALIDATION" --message RC_CHANNELS --limit 100
PYTHONPATH=src python -m dcmf.cli analyze "FINAL VALIDATION"
```

## SDR limitation to preserve in reports

SiK/RFD-style links can use frequency-hopping spread spectrum. A 2 MS/s
capture centered at 915 MHz cannot cover an entire wide configured hop range.
Before RF experiments, save both modem configurations, including
`MIN_FREQ`, `MAX_FREQ`, `NUM_CHANNELS`, `AIR_SPEED`, network ID, ECC/encryption,
and transmit power. State the USRP frequency/span and call the RF data a
partial-band observation unless the full hop range is demonstrably inside the
captured bandwidth.

## Parameter/file checklist for handoff

- flight-controller board and carrier photographs;
- firmware version/hash screenshot or text;
- QGC parameter backup and its exact path;
- QGC joystick screenshot/settings;
- TX16S model/EdgeTX version and exported model if permitted;
- ground and airborne modem readable labels/photos;
- both modem configuration backups;
- USRP model/serial and `uhd_usrp_probe` output;
- one final DCMF 1.0 validation experiment and quality/analysis artifacts.

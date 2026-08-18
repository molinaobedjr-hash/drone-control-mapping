# QGroundControl Setup and Validation

QGroundControl (QGC) is used to configure and independently verify the
controller-to-flight-controller path. DCMF then records the mapping experiment.
QGC is not required to remain open after persistent settings are saved.

Official references:

- [QGroundControl joystick setup](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/setup_view/joystick.html)
- [QGroundControl parameters](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/setup_view/parameters.html)
- [ArduPilot MAVLink RC input](https://ardupilot.org/dev/docs/mavlink-rcinput.html)
- [EdgeTX USB joystick mode](https://manual.edgetx.org/color-radios/model-settings/model-setup/usb-joystick)
- [EdgeTX stick mode and channel order](https://manual.edgetx.org/v2.9/edgetx-user-manual/user-manual-for-color-screen-radios/radio-settings/radio-setup)

## Known project configuration

The hardware validation established:

```text
QGC stick mode:       Mode 2
EdgeTX channel order: RETA
QGC send method:      MANUAL_CONTROL
Roll:                 RC channel 1
Pitch:                RC channel 2
Throttle:             RC channel 3
Yaw:                   RC channel 4
```

Relevant flight-controller values observed in the parameter set were
`RCMAP_ROLL=1`, `RCMAP_PITCH=2`, `RCMAP_THROTTLE=3`, and `RCMAP_YAW=4`.

Mode 2 says which physical stick owns throttle/yaw and roll/pitch. RETA says
how functions are ordered into channels. Do not try to convert RETA into a QGC
mode number; configure each in its own system and verify actual movement.

## Calibrate the TX16S in QGC

1. Connect the TX16S to the laptop and select USB **Joystick/HID** on the radio.
2. In QGC open **Vehicle Setup → Joystick**.
3. Select the TX16S joystick device.
4. Choose Mode 2 for this project.
5. Start calibration and follow every prompt exactly. Move the requested axis
   to full travel and leave it at the requested extreme until QGC advances.
6. Complete pitch, roll, yaw, and throttle. Do not move multiple sticks during
   one prompt.
7. Enable the joystick only after calibration completes.

If the wizard accepts throttle up but stalls at throttle down:

- watch the Raw Channel Monitor and confirm one axis reaches the opposite
  extreme;
- confirm the TX16S is exposing a real USB joystick, not storage/serial mode;
- check EdgeTX input/mix/output limits and throttle reversal;
- do not change EdgeTX channel order at random to force the wizard forward;
- cancel, center/return controls as requested, and restart after identifying
  the axis that does not span its full range.

Use **Send using MANUAL_CONTROL** for the validated laptop/radio architecture.
`RC_CHANNELS_OVERRIDE` is a different MAVLink input method and should not be
mixed into the same dataset without recording the architecture change.

## Prove the path in QGC

With the vehicle disarmed and propulsion safe:

1. Connect QGC through the ground telemetry radio.
2. Wait for parameters to finish downloading. A populated Parameters page and
   a complete Save-to-file operation indicate that QGC has received the
   parameter set.
3. Enable the calibrated joystick.
4. Open **Vehicle Setup → Radio** and move one control at a time.
5. Confirm roll moves channel 1, pitch channel 2, throttle channel 3, and yaw
   channel 4.
6. Disable the joystick. Channel movement must stop.
7. Re-enable it. Movement must return.
8. Save the vehicle parameters to a clearly chosen repository-external or
   project `backups/` path and record the path in experiment notes.

This proves the USB joystick → QGC `MANUAL_CONTROL` → ground telemetry modem →
airborne modem → flight controller path. It does not prove that DCMF is
transmitting until a DCMF experiment records TX `MANUAL_CONTROL` and returned
flight-controller data.

## Hand serial-port ownership to DCMF

QGC and DCMF cannot directly open the same `/dev/ttyUSB0` at the same time.
After saving parameters and completing QGC validation:

1. Disable the QGC joystick.
2. Disconnect the QGC vehicle link or close QGC.
3. If DCMF reports `Errno 16`, run:

   ```bash
   sudo fuser -v /dev/ttyUSB0
   ```

4. Start DCMF, select the same radio port at 57600 baud, and connect.
5. Wait for heartbeat and verify the vehicle is DISARMED.

Radio pairing/configuration is stored in the telemetry modems. Closing QGC does
not normally unpair them. LED activity may stop because QGC stopped sending
traffic. A DCMF connection should show incoming heartbeat; enabling guarded
output causes DCMF GCS heartbeat and `MANUAL_CONTROL` traffic.

## Match QGC and DCMF mappings

QGC joystick calibration and DCMF USB-axis calibration are independent. Both
must represent the same physical controls.

In DCMF choose **Tools → Calibrate TX16S**, capture baseline, and learn each
control separately. Move both directions/full travel during learning. After
saving, compare:

```text
physical roll      -> DCMF roll bar      -> MANUAL_CONTROL y -> RC1
physical pitch     -> DCMF pitch bar     -> MANUAL_CONTROL x -> RC2
physical throttle  -> DCMF throttle bar  -> MANUAL_CONTROL z -> RC3
physical yaw       -> DCMF yaw bar        -> MANUAL_CONTROL r -> RC4
```

DCMF normalized pitch/roll/yaw are `-1..+1`. DCMF throttle is also stored as
`-1..+1`, then converted to MAVLink `z=0..1000`. DCMF sets `buttons=0` and does
not send arm or flight-mode commands.

Do a short disarmed experiment, enable DCMF output, move one axis at a time,
stop, and inspect:

```bash
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT" --message MANUAL_CONTROL
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT" --message RC_CHANNELS
PYTHONPATH=src python -m dcmf.cli hex "EXPERIMENT" --message SERVO_OUTPUT_RAW
```

The TX records should change in the expected field. Returned RC values should
be plausible PWM values, not zeros. A decoded `RC_CHANNELS` record with
`chancount=0` and all zeros means the flight controller reported no usable RC
channel values in that record; DCMF treats zero as missing during analysis.

## Parameter and firmware record

The project previously observed a CubeOrangePlus running ArduCopter 4.5.4.
Firmware and parameter values can change, so each significant hardware change
should record:

- board/firmware version and git hash shown by QGC;
- full saved parameter file;
- `RCMAP_*`, serial baud/protocol, GCS failsafe, and RC override timeout;
- QGC joystick mode and send method;
- TX16S model name, EdgeTX version, channel order, and relevant mixes;
- ground and airborne modem settings, especially frequency range, channel
  count, network ID, air speed, ECC/encryption, and transmit power.

Do not change vehicle parameters solely because a DCMF graph looks unusual.
Preserve the record, compare with QGC, and change one understood setting at a
time.

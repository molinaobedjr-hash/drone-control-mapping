# DCMF Milestone 6 — TX16S Calibration and Saved Mapping

This milestone adds automatic axis learning.

## Tomorrow

1. Connect the TX16S in USB joystick/HID mode.
2. Launch DCMF.
3. Open `Tools -> Calibrate TX16S` or click the toolbar button.
4. Leave controls still.
5. Click `Learn Roll`, then move only roll strongly.
6. Repeat for Pitch, Yaw, and Throttle.
7. Use `Invert` if a control moves opposite the desired sign.
8. Click Save.

The mapping is written to:

`data/controller_mapping.json`

It is loaded automatically every time DCMF starts.

## Logged controller records

Controller events now contain both:

- original raw USB axes/buttons/hats
- mapped Roll/Pitch/Yaw/Throttle values

The raw data is deliberately preserved so mappings can be changed later
without losing the original controller samples.

## No hardware tonight

The application should launch normally without the TX16S. The calibration
dialog will simply state that it is waiting for controller samples.

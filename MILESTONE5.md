# DCMF Milestone 5 — UHD / USRP IQ Capture

This milestone adds a receive-only USRP capture backend.

## What it does

- Detects whether UHD command-line tools are installed.
- Discovers attached USRPs using `uhd_find_devices`.
- Lets the user select:
  - USRP
  - center frequency
  - sample rate
  - gain
- Launches UHD `rx_samples_to_file` in a background process.
- Saves raw complex int16 IQ (`sc16`) beneath:
  `data/iq/<experiment-id>/`
- Records SDR CAPTURE_START / CAPTURE_STOP events in SQLite.
- Uses the DCMF master software clock for event correlation.
- Can automatically start/stop IQ capture with an experiment.

## Important synchronization note

The CAPTURE_START and CAPTURE_STOP timestamps are host/software event
timestamps. This milestone does not claim PPS/GPSDO-level hardware
synchronization between the USRP sample clock and controller/MAVLink.

## Test tonight without the SDR

Run:

```bash
which uhd_find_devices
which rx_samples_to_file
python src/main.py
```

The application should still open if either command is missing. The SDR panel
will report which UHD capability is unavailable.

## Hardware validation tomorrow

With the USRP attached:

```bash
uhd_find_devices
uhd_usrp_probe
```

Then click Refresh inside DCMF. The USRP should appear in the selector.

For the initial 915 MHz survey, the GUI defaults remain:

- Center: 915 MHz
- Sample rate: 2 MS/s
- Gain: 30 dB

Those are starting settings, not guaranteed optimal values.

## IQ storage rate

The selected `short`/sc16 format stores I and Q as signed 16-bit values:
4 bytes per complex sample. At 2 MS/s this is about 8 MB/s, or about
480 MB/minute, before filesystem overhead.

Use short controlled captures during early validation.

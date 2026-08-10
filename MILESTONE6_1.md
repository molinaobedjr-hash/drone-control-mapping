# DCMF v0.5.1 — Kali UHD Compatibility Fix

Kali/Debian may install UHD example programs under:

`/usr/libexec/uhd/examples/`

instead of placing them in the shell PATH.

DCMF now checks both PATH and common Debian/Kali UHD example directories.

Your current machine has:

- `/usr/bin/uhd_find_devices`
- `/usr/libexec/uhd/examples/rx_samples_to_file`

so after installing this patch, the SDR panel should report:

`UHD ready; no USRP detected`

while the USRP is disconnected.

Tomorrow, with the B210/USRP attached, click Refresh and DCMF should invoke
`uhd_find_devices` and populate the device selector.

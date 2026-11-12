#!/usr/bin/env python3
"""Passive serial logger for the badge: appends everything it prints to a file.

    python3 trmnl/tools/serial_log.py /dev/cu.usbmodem101 badge.log [seconds]

It never writes to the badge (no reset, no Ctrl-C) and reconnects if the USB port drops,
which `mpremote repl` does not do. Run it in the background, then `tail` the file.
Needs pyserial: run it with mpremote's interpreter if that is where pyserial lives,
e.g. `$(head -1 $(which mpremote) | sed 's/^#!//') trmnl/tools/serial_log.py ...`.
mpremote and this logger cannot share the port; stop the logger before using mpremote.
"""
import sys
import time

import serial

port, out = sys.argv[1], sys.argv[2]
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 3600.0
end = time.time() + seconds
log = open(out, "ab", buffering=0)
ser = None
while time.time() < end:
    try:
        if ser is None:
            ser = serial.Serial(port, 115200, timeout=0.2, dsrdtr=False, rtscts=False)
            log.write(b"\n[logger: connected]\n")
        data = ser.read(4096)
        if data:
            log.write(data)
    except (serial.SerialException, OSError):
        if ser is not None:
            log.write(b"\n[logger: connection lost, retrying]\n")
            try:
                ser.close()
            except Exception:
                pass
        ser = None
        time.sleep(1)

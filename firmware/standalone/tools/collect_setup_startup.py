"""Read one K151 setup-only startup verdict from the selected serial port."""

import argparse
import json
import re
import time

_BOOT = ("policy", "chip", "identity", "slot", "psram", "security", "flash", "nvs", "ready")
_SETUP = (
    "idle",
    "preconditions",
    "owner_task",
    "board_bus",
    "lvgl",
    "panel",
    "view",
    "presence_frame",
    "head",
    "clock",
    "ready",
)
_RECORD = re.compile(rb"K151_SETUP_STARTUP_PROBE_V1 ([0-8]) ([0-9]|10) ([01])\r?\n")
_LIMIT = 96


def read_report(port, *, clock=time.monotonic):
    deadline = clock() + 15
    pending = bytearray()
    dropping = False
    while clock() < deadline:
        chunk = port.read_until(expected=b"\n", size=_LIMIT - len(pending))
        if clock() >= deadline:
            break
        if dropping:
            dropping = not chunk.endswith(b"\n")
            continue
        pending.extend(chunk)
        if not pending.endswith(b"\n"):
            if len(pending) >= _LIMIT:
                pending.clear()
                dropping = True
            continue
        match = _RECORD.fullmatch(bytes(pending))
        pending.clear()
        if match is None:
            continue
        boot, setup, cleanup = map(int, match.groups())
        if (boot == 8 and setup == 0) or (boot != 8 and (setup != 0 or cleanup != 1)):
            continue
        return {"boot": _BOOT[boot], "setup": _SETUP[setup], "cleanup": bool(cleanup)}
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Exact port for the approved probe")
    args = parser.parse_args(argv)

    import serial

    try:
        port = serial.Serial(port=None, baudrate=115200, timeout=0.2)
        port.port = args.port
        port.dtr = port.rts = False
        with port:
            report = read_report(port)
    except (OSError, ValueError):
        print(json.dumps({"failure": "serial_io"}))
        return 1
    if report is None:
        print(json.dumps({"failure": "startup_report_missing"}))
        return 1
    print(json.dumps(report))
    return int(not report["cleanup"])


if __name__ == "__main__":
    raise SystemExit(main())

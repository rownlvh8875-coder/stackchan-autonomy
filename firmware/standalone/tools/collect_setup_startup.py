"""Read one K151 setup-only startup verdict from the selected serial port."""

import argparse
import json
import re
import time

from scps_usb_wire import (
    Frame,
    Op,
    ScpsInvalidFrame,
    ScpsResponseTimeout,
    ScpsWireError,
    encode,
    expect,
)

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
_SCPS_RECORD = re.compile(
    rb"(?:^|\n)K151_SETUP_STARTUP_PROBE_V2 ([0-8]) ([0-9]|10) ([01]) ([0-2])\r?\n"
)
_TX = ("skipped", "unconfirmed", "drained")
_LIMIT = 96
_OBSERVATION_BYTES = 8192
_SCPS_SECONDS = 20
_PROBE_PAYLOAD = bytes(86)
_PROBE_FRAME = encode(Frame(Op.DEVICE_HELLO, _PROBE_PAYLOAD))


def _startup_result(boot, setup, cleanup):
    if (boot == 8 and setup == 0) or (boot != 8 and (setup != 0 or cleanup != 1)):
        return None
    return {"boot": _BOOT[boot], "setup": _SETUP[setup], "cleanup": bool(cleanup)}


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
        result = _startup_result(*map(int, match.groups()))
        if result is not None:
            return result
    return None


def _scps_startup_result(observed):
    for match in _SCPS_RECORD.finditer(observed):
        boot, setup, cleanup, tx = map(int, match.groups())
        result = _startup_result(boot, setup, cleanup)
        if result is not None and (tx == 0 or (setup == 10 and cleanup == 1)):
            return {**result, "tx": _TX[tx]}
    return None


def read_scps_report(port, *, clock=time.monotonic):
    """Use the production parser once and passively look for the known probe frame."""
    observed = bytearray()
    deadline = clock() + _SCPS_SECONDS

    class Receiver:
        def read(self, size):
            remaining = _OBSERVATION_BYTES - len(observed)
            if clock() >= deadline or remaining == 0:
                raise ScpsResponseTimeout("probe observation ended")
            requested = min(size, remaining)
            data = port.read(requested)
            if not isinstance(data, bytes) or len(data) > requested:
                raise ScpsInvalidFrame("invalid serial read during probe")
            observed.extend(data)
            return data

    receiver = Receiver()
    first_response = "serial_io"
    try:
        hello = expect(receiver, Op.DEVICE_HELLO, _SCPS_SECONDS)
        first_response = (
            "probe_received" if hello.payload == _PROBE_PAYLOAD else "unexpected_probe_payload"
        )
    except ScpsWireError as exc:
        first_response = exc.diagnostic
    except OSError:
        pass

    # A framing rejection remains the verdict even if the fixture appears
    # later. Only local metadata from this passive observation is returned.
    startup = _scps_startup_result(observed)
    while startup is None and first_response != "serial_io":
        try:
            if receiver.read(_LIMIT):
                startup = _scps_startup_result(observed)
        except (ScpsWireError, OSError):
            break
    probe_offset = observed.find(_PROBE_FRAME)
    return {
        "first_response": first_response,
        "probe_offset": None if probe_offset < 0 else probe_offset,
        "startup": startup,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Exact port for the approved probe")
    parser.add_argument("--scps-probe", action="store_true", help="Read the V2 SCPS startup probe")
    args = parser.parse_args(argv)

    import serial

    try:
        port = serial.Serial(port=None, baudrate=115200, timeout=0.2)
        port.port = args.port
        port.dtr = port.rts = False
        with port:
            report = read_scps_report(port) if args.scps_probe else read_report(port)
    except (OSError, ValueError):
        print(json.dumps({"failure": "serial_io"}))
        return 1
    if report is None:
        print(json.dumps({"failure": "startup_report_missing"}))
        return 1
    print(json.dumps(report))
    if args.scps_probe:
        startup = report["startup"]
        return int(
            report["first_response"] != "probe_received"
            or startup is None
            or startup["tx"] != "drained"
        )
    return int(not report["cleanup"])


if __name__ == "__main__":
    raise SystemExit(main())

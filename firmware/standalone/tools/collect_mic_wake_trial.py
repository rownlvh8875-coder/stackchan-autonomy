"""Receive one authorized K151 trial. Keep fixed counts and discard raw serial bytes."""

import argparse
import json
import re
import time
from pathlib import Path

from wake_bench_trace import parse_mic_wake_trial_report

SCOPE = "ONE_MIC_WAKE_TRIAL_AND_OTA1_RESTORE"
WIRE_LIMIT = 512


def receive_once(port, announce, *, before_start=lambda: None, clock=time.monotonic):
    deadline = clock() + 15
    started = listening = complete = False
    report = None
    pending = bytearray()
    try:
        if port.write(b"HELLO\n") != len(b"HELLO\n"):
            raise ValueError("Incomplete challenge request")
        while clock() < deadline:
            pending.extend(port.read_until(expected=b"\n", size=WIRE_LIMIT))
            if len(pending) > WIRE_LIMIT or (
                len(pending) == WIRE_LIMIT and not pending.endswith(b"\n")
            ):
                raise ValueError("Serial record exceeded the fixed wire limit")
            if not pending.endswith(b"\n"):
                continue
            try:
                record = json.loads(pending)
            except (UnicodeError, ValueError):
                continue
            finally:
                pending.clear()
            if not isinstance(record, dict):
                continue
            marker = record.get("mic_trial")
            if marker == "WAIT_LOCAL_START":
                nonce = record.get("nonce")
                if (
                    started
                    or set(record) != {"mic_trial", "nonce", "wait_ms"}
                    or record.get("wait_ms") != 60000
                    or not isinstance(nonce, str)
                    or re.fullmatch(r"[0-9A-F]{8}", nonce) is None
                    or nonce == "00000000"
                ):
                    raise ValueError("Invalid or repeated local challenge")
                start = f"START {nonce}\n".encode("ascii")
                before_start()
                started = True
                if port.write(start) != len(start):
                    raise ValueError("Incomplete START")
                deadline = clock() + 12
            elif marker == "LISTEN_NOW":
                if (
                    not started
                    or listening
                    or report is not None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected listening marker")
                listening = True
                announce()
            elif "mic_wake_trial" in record:
                if not started or report is not None:
                    raise ValueError("Unexpected or repeated trial result")
                report = parse_mic_wake_trial_report(record)
                if report["result"] in {"detected", "not_detected"} and not listening:
                    raise ValueError("Capture result preceded the listening marker")
            elif marker == "HOLD_UNTIL_RESET":
                if (
                    report is None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or (record["operating_admission"] is not False)
                ):
                    raise ValueError("Trial did not finish with a verified result")
                complete = True
                return report
        raise TimeoutError("Trial deadline elapsed")
    finally:
        if started and not complete:
            try:
                port.write(b"STOP\n")
            except OSError:
                pass


def verified_port(directory):
    def record(name):
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))

    manifest = record("review-manifest.json")
    approved = record("approval.json")
    installed = record("install-verified.json")
    digest = manifest["image_sha256"]
    port = manifest["port"]
    if not (
        re.fullmatch(r"[0-9a-f]{64}", digest)
        and re.fullmatch(r"COM[1-9][0-9]*", port)
        and approved.get("approved") is True
        and approved.get("scope") == SCOPE
        and approved.get("image_sha256") == installed.get("image_sha256") == digest
        and installed.get("independent_verify_passed") is True
        and installed.get("offset") == 0x510000
        and installed.get("port") == port
    ):
        raise ValueError("Scoped approval and verified install are required")
    return port, digest


def open_port(serial, name, *, clock=time.monotonic, wait=time.sleep):
    deadline = clock() + 6
    while clock() < deadline:
        port = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
        port.port = name
        port.dtr = port.rts = False
        try:
            port.open()
        except serial.SerialException:
            port.close()
            wait(0.15)
        else:
            return port
    raise TimeoutError("USB port did not return")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        port_name, digest = verified_port(args.review_dir)
        intent = args.review_dir / "mic-receive-intent.json"
        if intent.exists():
            raise ValueError("A START was already attempted")

        def reserve():
            with intent.open("x", encoding="utf-8") as file:
                json.dump({"image_sha256": digest}, file)

        import serial

        port = open_port(serial, port_name)
        try:
            report = receive_once(
                port,
                lambda: print("지금 Hi StackChan을 한 번 말해 주세요.", flush=True),
                before_start=reserve,
            )
        finally:
            port.close()
        with (args.review_dir / "mic-result.json").open("x", encoding="utf-8") as file:
            json.dump(report, file)
        print(json.dumps(report))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, KeyboardInterrupt):
        print("Microphone trial stopped or denied. Check the reviewed restore procedure.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

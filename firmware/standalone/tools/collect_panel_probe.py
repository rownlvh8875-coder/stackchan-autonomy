"""Collect a separately approved, single K151 panel/head/STOP diagnostic."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

SCOPE = "ONE_PANEL_HEAD_STOP_PROBE_AND_OTA1_RESTORE"
MODE = "PANEL_HEAD_STOP_ONLY"
KIND = "REVIEW_ONLY_PANEL_PROBE_V1"
PROTOCOL = "K151_PANEL_HEAD_STOP_PROBE_NOT_OPERATIONAL"
STOP_SCOPE = "ONE_PANEL_SCREEN_STOP_PROBE_AND_OTA1_RESTORE"
STOP_MODE = "PANEL_SCREEN_STOP_ONLY"
STOP_KIND = "REVIEW_ONLY_PANEL_SCREEN_STOP_V1"
STOP_PROTOCOL = "K151_PANEL_SCREEN_STOP_PROBE_NOT_OPERATIONAL"
STAGES = {
    "PANEL_FRAME_READY": "숫자가 보이면 머리 윗면에 손가락을 3초 가볍게 댄 뒤 떼세요.",
    "HEAD_CONFIRMED": "머리 터치가 확인됐습니다. 화면 터치 안내를 기다려 주세요.",
    "WAIT_SCREEN_STOP": "지금 로봇 화면을 한 번 가볍게 터치해 주세요.",
}
RESULTS = {
    "I2C_SETUP_FAILED",
    "LVGL_ALREADY_OWNED",
    "PANEL_START_FAILED",
    "PANEL_FRAME_FAILED",
    "HEAD_PREPARE_FAILED",
    "HEAD_READ_OR_TIMING_FAILED",
    "STOP_PROMPT_FRAME_FAILED",
    "DISPLAY_STOP_ARM_FAILED",
    "EARLY_DISPLAY_IRQ",
    "HOST_STOP_OR_DEADLINE",
    "DISPLAY_STOP_LATCHED",
}
EARLY_RESULTS = {
    "RUNNING_LOCATION_OR_CHIP_DENIED": "device_location_denied",
    "USB_SETUP_FAILED": "device_usb_setup_failed",
    "NO_LOCAL_START": "device_no_start",
}
WIRE_LIMIT = 512


class PanelProbeFailure(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.report = {"failure": reason}


def receive_once(port, announce, reserve, clock=time.monotonic, *, stop_only=False):
    protocol = STOP_PROTOCOL if stop_only else PROTOCOL
    challenge = "WAIT_SCREEN_STOP_START" if stop_only else "WAIT_LOCAL_START"
    expected_stages = ("WAIT_SCREEN_STOP",) if stop_only else tuple(STAGES)
    next_hello = clock()
    deadline = next_hello + 8
    outstanding = 0
    nonce = None
    pending = bytearray()
    stages = []
    result = None
    evidence = {"boot_seen": False, "usb_ready": False, "start_attempted": False}
    try:
        while clock() < deadline:
            if nonce is None and clock() >= next_hello:
                if port.write(b"HELLO\n") != 6:
                    raise PanelProbeFailure("hello_write_incomplete")
                outstanding += 1
                next_hello = clock() + 0.5

            pending.extend(port.read_until(expected=b"\n", size=WIRE_LIMIT - len(pending)))
            if clock() >= deadline:
                break
            if len(pending) > WIRE_LIMIT or (
                len(pending) == WIRE_LIMIT and not pending.endswith(b"\n")
            ):
                raise PanelProbeFailure("wire_record_too_long")
            if not pending.endswith(b"\n"):
                continue
            try:
                if pending.strip() == protocol.encode("ascii"):
                    evidence["boot_seen"] = True
                    continue
                record = json.loads(pending)
            except (UnicodeError, ValueError):
                continue
            finally:
                pending.clear()
            if not isinstance(record, dict):
                continue

            marker = record.get("probe")
            if marker == "PANEL_USB_READY" and record.get("operating_admission") is False:
                evidence["usb_ready"] = True
            elif marker in ("WAIT_LOCAL_START", "WAIT_SCREEN_STOP_START"):
                if marker != challenge:
                    raise PanelProbeFailure("unexpected_trial_mode")
                offered = record.get("nonce")
                if (
                    not outstanding
                    or not isinstance(offered, str)
                    or not re.fullmatch("[0-9A-F]{8}", offered)
                    or offered == "00000000"
                    or (nonce is not None and offered != nonce)
                ):
                    raise PanelProbeFailure("invalid_or_changed_challenge")
                outstanding -= 1
                evidence["usb_ready"] = True
                if nonce is not None:
                    continue
                try:
                    reserve()
                except OSError:
                    raise PanelProbeFailure("start_record_failed") from None
                if clock() >= deadline:
                    raise PanelProbeFailure("start_deadline_elapsed")
                nonce = offered
                evidence["start_attempted"] = True
                start = f"START {nonce}\n".encode("ascii")
                if port.write(start) != len(start):
                    raise PanelProbeFailure("start_write_incomplete")
                deadline = clock() + 12
            elif isinstance(marker, str) and marker in STAGES:
                if (
                    nonce is None
                    or result is not None
                    or (*stages, marker) != expected_stages[: len(stages) + 1]
                ):
                    raise PanelProbeFailure("unexpected_stage")
                stages.append(marker)
                announce(STAGES[marker])
            elif "result" in record:
                label = record["result"]
                if nonce is None and isinstance(label, str) and label in EARLY_RESULTS:
                    raise PanelProbeFailure(EARLY_RESULTS[label])
                if (
                    nonce is None
                    or result is not None
                    or not isinstance(label, str)
                    or label not in RESULTS
                    or record.get("operating_admission") is not False
                    or type(record.get("cleanup")) is not bool
                    or (label == "DISPLAY_STOP_LATCHED" and tuple(stages) != expected_stages)
                ):
                    raise PanelProbeFailure("invalid_result")
                result = {"result": label, "cleanup": record["cleanup"]}
            elif marker == "HOLD_UNTIL_RESET":
                if result is None or record.get("operating_admission") is not False:
                    raise PanelProbeFailure("invalid_hold")
                return {**result, **evidence, "stages": stages, "hold_observed": True}
        if nonce is not None:
            raise PanelProbeFailure("trial_report_timeout")
        if evidence["usb_ready"] or evidence["boot_seen"]:
            raise PanelProbeFailure("challenge_timeout")
        raise PanelProbeFailure("no_boot_or_usb_reply")
    except (OSError, PanelProbeFailure) as exc:
        if outstanding or nonce is not None:
            try:
                port.write(b"STOP\n")
            except (OSError, ValueError):
                pass
        failure = (
            exc if isinstance(exc, PanelProbeFailure) else PanelProbeFailure("serial_io_failed")
        )
        failure.report.update(evidence, stages=stages)
        raise failure from None


def verified_port(directory):
    def load(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    review, approval, installed = (
        load("review-manifest.json"),
        load("approval.json"),
        load("install-verified.json"),
    )
    digest = review["image_sha256"]
    port = review["port"]
    stop_only = review.get("kind") == STOP_KIND
    scope, mode, kind, protocol, image_name = (
        (STOP_SCOPE, STOP_MODE, STOP_KIND, STOP_PROTOCOL, "k151_screen_stop_probe.bin")
        if stop_only
        else (SCOPE, MODE, KIND, PROTOCOL, "k151_panel_probe.bin")
    )
    if not (
        isinstance(digest, str)
        and re.fullmatch("[0-9a-f]{64}", digest)
        and port == "COM3"
        and review.get("kind") == kind
        and review.get("expected_protocol") == protocol
        and review.get("scope") == approval.get("scope") == scope
        and review.get("operator_mode") == approval.get("operator_mode") == mode
        and all(
            record.get("review_id") == directory.name for record in (review, approval, installed)
        )
        and approval.get("approved") is True
        and approval.get("image_sha256") == digest == installed.get("image_sha256")
        and installed.get("independent_verify_passed") is True
        and installed.get("offset") == 0x510000
        and installed.get("port") == port
    ):
        raise ValueError("Reviewed scope and independent install verification required")
    image = directory / "artifact" / image_name
    if (
        image.stat().st_size != review["write_bytes"]
        or hashlib.sha256(image.read_bytes()).hexdigest() != digest
    ):
        raise ValueError("Reviewed image mismatch")
    return port, digest, stop_only


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, required=True)
    directory = parser.parse_args().review_dir
    intent = directory / "panel-trial-intent.json"
    result_file = directory / "panel-result.json"
    try:
        name, digest, stop_only = verified_port(directory)
        if any(path.exists() for path in (intent, result_file, directory / "restore-started.json")):
            raise ValueError("Trial already attempted")
        import serial
    except (ImportError, OSError, TypeError, ValueError, KeyError, AttributeError):
        print('{"failure":"review_binding_unavailable"}')
        return 1

    def reserve():
        with intent.open("x", encoding="utf-8") as out:
            json.dump({"image_sha256": digest, "scope": STOP_SCOPE if stop_only else SCOPE}, out)

    port = serial.Serial(port=None, baudrate=115200, timeout=0.08, write_timeout=0.5)
    port.port = name
    port.dtr = port.rts = False
    try:
        port.open()
    except (OSError, ValueError):
        report = {"failure": "serial_open_failed"}
    else:
        try:
            report = receive_once(
                port, lambda message: print(message, flush=True), reserve, stop_only=stop_only
            )
        except PanelProbeFailure as exc:
            report = exc.report
        finally:
            port.close()
    with result_file.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
    print(json.dumps(report))
    return 0 if report.get("result") == "DISPLAY_STOP_LATCHED" and report["cleanup"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Receive one authorized K151 trial. Keep fixed counts and discard raw serial bytes."""

import argparse
import json
import re
import time
from pathlib import Path

from wake_bench_trace import parse_mic_wake_trial_report

SCOPE = "ONE_MIC_WAKE_TRIAL_AND_OTA1_RESTORE"
QUESTION_SCOPE = "ONE_MIC_QUESTION_TRIAL_AND_OTA1_RESTORE"
WAKE_ONLY_CONTROL_SCOPE = "ONE_WAKE_ONLY_CONTROL_AND_OTA1_RESTORE"
QUESTION_ONLY_SCOPE = "ONE_QUESTION_ONLY_TRIAL_AND_OTA1_RESTORE"
QUESTION_PROTOCOL = "MIC_QUESTION_TRIAL_V1"
QUESTION_ONLY_PROTOCOL = "MIC_QUESTION_ONLY_TRIAL_V1"
SILENT_TX_SCOPE = "ONE_SILENT_TX_PROBE_AND_OTA1_RESTORE"
SILENT_TX_PROTOCOL = "K151_SILENT_TX_V1"
SPEAKER_SCOPE = "ONE_SYNTHETIC_SPEAKER_PROBE_AND_OTA1_RESTORE"
SPEAKER_PROTOCOL = "K151_SPEAKER_V1"
SILENT_TX_RESULTS = {
    "denied",
    "stopped",
    "channel_failed",
    "preload_failed",
    "callback_failed",
    "enable_failed",
    "timeout",
    "invalid_event",
    "clock_fault",
    "cleanup_failed",
    "two_descriptors_observed",
}
SPEAKER_RESULTS = {
    "denied",
    "stopped",
    "codec_prepare_failed",
    "clock_fault",
    "amplifier_start_failed",
    "transfer_failed",
    "mute_confirmation_failed",
    "cleanup_failed",
    "dma_and_mute_observed",
}
WIRE_LIMIT = 512
QUESTION_BEFORE_CUE = {"not_run", "memory_denied", "prepare_failed", "open_failed", "quiet_timeout"}
QUESTION_AFTER_CUE = {"no_endpoint", "endpoint"}
QUESTION_ANY_TIME = {"stopped", "clock_fault", "read_failed", "release_failed"}
CLEAN_QUESTION_RESULTS = {
    "not_run",
    "stopped",
    "memory_denied",
    "endpoint",
    "no_endpoint",
    "quiet_timeout",
}


def validate_question_report(record, *, cue_seen, wake=None):
    result = record.get("result")
    cleanup = record.get("codec_cleanup_unverified")
    protocol = QUESTION_PROTOCOL if wake is not None else QUESTION_ONLY_PROTOCOL
    cue_results = QUESTION_AFTER_CUE if cue_seen else QUESTION_BEFORE_CUE
    if (
        set(record)
        != {"mic_question_trial", "result", "codec_cleanup_unverified", "operating_admission"}
        or record.get("mic_question_trial") != protocol
        or record.get("operating_admission") is not False
        or type(cleanup) is not bool
        or not isinstance(result, str)
        or result not in QUESTION_ANY_TIME | cue_results
        or (cleanup and result in CLEAN_QUESTION_RESULTS)
    ):
        raise ValueError("Invalid question trial report")
    if wake is None:
        if result == "not_run":
            raise ValueError("The question-only trial has no wake stage")
    elif wake["mic_wake_trial"] not in (
        "MIC_WAKE_TRIAL_V2",
        "MIC_WAKE_TRIAL_V3",
        "MIC_WAKE_TRIAL_V4",
    ) or (wake["result"] == "detected") != (result != "not_run"):
        raise ValueError("Invalid preceding wake result")
    return record


def validate_output_report(record, *, speaker):
    field, protocol, results = (
        ("speaker_probe", SPEAKER_PROTOCOL, SPEAKER_RESULTS)
        if speaker
        else ("tx_dma_probe", SILENT_TX_PROTOCOL, SILENT_TX_RESULTS)
    )
    result = record.get("result")
    if (
        set(record) != {field, "result", "operating_admission"}
        or record.get(field) != protocol
        or record.get("operating_admission") is not False
        or not isinstance(result, str)
        or result not in results
    ):
        raise ValueError("Invalid output diagnostic result")
    return record


def receive_once(
    port,
    announce,
    *,
    announce_question=None,
    wake_only_control=False,
    question_only=False,
    silent_tx=False,
    speaker=False,
    before_start=lambda: None,
    clock=time.monotonic,
):
    question_mode = announce_question is not None
    output_only = silent_tx or speaker
    if (wake_only_control or question_only) and not question_mode:
        raise ValueError("Trial requires a question-phase cue")
    if sum((wake_only_control, question_only, silent_tx, speaker)) > 1 or (
        output_only and question_mode
    ):
        raise ValueError("Select a single trial mode")
    if speaker:
        challenge = "WAIT_SPEAKER_LOCAL_START"
    elif silent_tx:
        challenge = "WAIT_SILENT_TX_LOCAL_START"
    elif question_only:
        challenge = "WAIT_QUESTION_ONLY_START"
        question_cue = "QUESTION_ONLY_NOW"
    elif wake_only_control:
        challenge = "WAIT_WAKE_ONLY_CONTROL"
        question_cue = "QUIET_OBSERVATION_NOW"
    else:
        challenge = "WAIT_QUESTION_LOCAL_START" if question_mode else "WAIT_LOCAL_START"
        question_cue = "QUESTION_NOW"
    next_hello = clock()
    deadline = next_hello + 15
    waiting_replies = 0
    accepted_nonce = None
    started = listening = complete = False
    report = question_report = None
    question_cued = False
    pending = bytearray()
    try:
        while clock() < deadline:
            if not started and clock() >= next_hello:
                if port.write(b"HELLO\n") != len(b"HELLO\n"):
                    raise ValueError("Incomplete challenge request")
                waiting_replies += 1
                next_hello = clock() + 0.5
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
            if marker in (
                "WAIT_LOCAL_START",
                "WAIT_QUESTION_LOCAL_START",
                "WAIT_WAKE_ONLY_CONTROL",
                "WAIT_QUESTION_ONLY_START",
                "WAIT_SILENT_TX_LOCAL_START",
                "WAIT_SPEAKER_LOCAL_START",
            ):
                nonce = record.get("nonce")
                if (
                    marker != challenge
                    or not waiting_replies
                    or set(record) != {"mic_trial", "nonce", "wait_ms"}
                    or record.get("wait_ms") != 60000
                    or not isinstance(nonce, str)
                    or re.fullmatch(r"[0-9A-F]{8}", nonce) is None
                    or nonce == "00000000"
                ):
                    raise ValueError("Invalid or repeated local challenge")
                waiting_replies -= 1
                if started:
                    if nonce != accepted_nonce:
                        raise ValueError("Diagnostic restarted after START")
                    continue
                start = f"START {nonce}\n".encode("ascii")
                before_start()
                accepted_nonce = nonce
                started = True
                if port.write(start) != len(start):
                    raise ValueError("Incomplete START")
                deadline = clock() + 12
            elif marker == "LISTEN_NOW":
                if (
                    not started
                    or question_only
                    or output_only
                    or listening
                    or report is not None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected listening marker")
                listening = True
                announce()
            elif marker in ("QUESTION_NOW", "QUIET_OBSERVATION_NOW", "QUESTION_ONLY_NOW"):
                if (
                    not question_mode
                    or marker != question_cue
                    or not started
                    or (not question_only and not listening)
                    or question_cued
                    or report is not None
                    or question_report is not None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected question marker")
                question_cued = True
                announce_question()
            elif "tx_dma_probe" in record or "speaker_probe" in record:
                if not output_only or not started or report is not None:
                    raise ValueError("Unexpected or repeated output result")
                report = validate_output_report(record, speaker=speaker)
            elif "mic_wake_trial" in record:
                if output_only or question_only or not started or report is not None:
                    raise ValueError("Unexpected or repeated trial result")
                report = parse_mic_wake_trial_report(record)
                if report["result"] in {"detected", "not_detected"} and not listening:
                    raise ValueError("Capture result preceded the listening marker")
            elif "mic_question_trial" in record:
                if (
                    not started
                    or not question_mode
                    or (not question_only and report is None)
                    or question_report is not None
                ):
                    raise ValueError("Unexpected or repeated question report")
                question_report = validate_question_report(
                    record, cue_seen=question_cued, wake=report
                )
            elif marker == "HOLD_UNTIL_RESET":
                if (
                    (not question_only and report is None)
                    or (question_mode and question_report is None)
                    or set(record) != {"mic_trial", "operating_admission"}
                    or (record["operating_admission"] is not False)
                ):
                    raise ValueError("Trial did not finish with a verified result")
                complete = True
                if question_only:
                    return question_report
                return {"wake": report, "question": question_report} if question_mode else report
        raise TimeoutError("Trial deadline elapsed")
    finally:
        if started and not complete:
            try:
                port.write(b"STOP\n")
            except OSError:
                pass


def verified_port(
    directory,
    *,
    question=False,
    wake_only_control=False,
    question_only=False,
    silent_tx=False,
    speaker=False,
):
    if sum((question, wake_only_control, question_only, silent_tx, speaker)) > 1:
        raise ValueError("Select a single trial mode")

    def record(name):
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))

    manifest = record("review-manifest.json")
    approved = record("approval.json")
    installed = record("install-verified.json")
    digest = manifest["image_sha256"]
    port = manifest["port"]
    protocol = QUESTION_ONLY_PROTOCOL if question_only else QUESTION_PROTOCOL
    if silent_tx or speaker:
        if speaker:
            scope = SPEAKER_SCOPE
            protocol = SPEAKER_PROTOCOL
            expected_kind = "REVIEW_ONLY_SPEAKER_PROBE_V1"
            if any(
                item.get("operator_mode") != "SYNTHETIC_SPEAKER_ONLY"
                for item in (manifest, approved)
            ):
                raise ValueError("Synthetic speaker mode must be explicitly scoped")
        else:
            scope = SILENT_TX_SCOPE
            protocol = SILENT_TX_PROTOCOL
            expected_kind = "REVIEW_ONLY_SILENT_TX_PROBE_V1"
        review_id = directory.name
        if any(item.get("review_id") != review_id for item in (manifest, approved, installed)):
            raise ValueError("Output approval and installation must refer to this review")
    elif question_only:
        scope = QUESTION_ONLY_SCOPE
        expected_kind = "REVIEW_ONLY_QUESTION_ONLY_TRIAL_V1"
    elif wake_only_control:
        scope = WAKE_ONLY_CONTROL_SCOPE
        expected_kind = "REVIEW_ONLY_WAKE_ONLY_CONTROL_V1"
    elif question:
        scope = QUESTION_SCOPE
        expected_kind = "REVIEW_ONLY_MIC_QUESTION_TRIAL_V1"
    else:
        scope = SCOPE
        expected_kind = None
    if expected_kind and not (
        manifest.get("kind") == expected_kind
        and manifest.get("scope") == scope
        and manifest.get("expected_protocol") == protocol
    ):
        raise ValueError("Review manifest for the selected trial mode is required")
    if not (
        re.fullmatch(r"[0-9a-f]{64}", digest)
        and re.fullmatch(r"COM[1-9][0-9]*", port)
        and approved.get("approved") is True
        and approved.get("scope") == scope
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--question", action="store_true")
    mode.add_argument("--wake-only-control", action="store_true")
    mode.add_argument("--question-only", action="store_true")
    mode.add_argument("--silent-tx", action="store_true")
    mode.add_argument("--speaker", action="store_true")
    args = parser.parse_args()
    try:
        port_name, digest = verified_port(
            args.review_dir,
            question=args.question,
            wake_only_control=args.wake_only_control,
            question_only=args.question_only,
            silent_tx=args.silent_tx,
            speaker=args.speaker,
        )
        intent = args.review_dir / "mic-receive-intent.json"
        if intent.exists():
            raise ValueError("A START was already attempted")

        def reserve():
            with intent.open("x", encoding="utf-8") as file:
                json.dump({"image_sha256": digest}, file)

        import serial

        def cue_question():
            if args.wake_only_control:
                print("질문 없이 잠시 조용히 기다려 주세요.", flush=True)
            else:
                print("지금 짧은 질문을 한 번 말하고 잠시 기다려 주세요.", flush=True)

        if args.speaker:
            print("SPEAKER_PREPARE", flush=True)
        port = open_port(serial, port_name)
        try:
            report = receive_once(
                port,
                lambda: print("지금 Hi StackChan을 한 번 말해 주세요.", flush=True),
                before_start=reserve,
                announce_question=(
                    cue_question
                    if args.question or args.wake_only_control or args.question_only
                    else None
                ),
                wake_only_control=args.wake_only_control,
                question_only=args.question_only,
                silent_tx=args.silent_tx,
                speaker=args.speaker,
            )
        finally:
            port.close()
        if args.speaker:
            result_file = "speaker-result.json"
        else:
            result_file = "tx-dma-result.json" if args.silent_tx else "mic-result.json"
        with (args.review_dir / result_file).open("x", encoding="utf-8") as file:
            json.dump(report, file)
        print(json.dumps(report))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, KeyboardInterrupt):
        print("Diagnostic stopped or denied. Check the reviewed restore procedure.")
        return 1
    return int(args.speaker and report["result"] != "dma_and_mute_observed")


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate one K151 diagnostic artifact without opening a device."""

import argparse
import json
from pathlib import Path

import check_resource_bench
from check_board_probe import validate_slot
from check_idf_build import validate
from esp_app_image import SLOT_OFFSET, bind_source_head, inspect_envelope, validate_source_head


def inspect_image(
    app: bytes,
    elf_sha256: str,
    partition_csv: str,
    *,
    question=False,
    wake_only_control=False,
    question_only=False,
    silent_tx=False,
    speaker=False,
    speaker_stop=False,
) -> dict:
    if sum((question, wake_only_control, question_only, silent_tx, speaker, speaker_stop)) > 1:
        raise ValueError("Select a single trial image")
    if speaker_stop:
        envelope, _ = inspect_envelope(app, elf_sha256, b"k151_speaker_stop_probe")
        protocols = {
            "K151_SPEAKER_STOP_V1": (b"WAIT_SPEAKER_SCREEN_STOP_START\0",),
            "K151_SPEAKER_STOP_V2": (
                b"WAIT_SPEAKER_SCREEN_STOP_PROGRESS_START\0",
                b'"SPEAKER_STOP_PLAYING"',
                b'"pcm_blocks"',
                b'"dma_complete"',
                b'"standby_confirmed"',
            ),
        }
        observed = [protocol for protocol in protocols if protocol.encode() + b'"' in app]
        required = (
            b"K151_SPEAKER_STOP_PROBE_NOT_OPERATIONAL\0",
            b'"SPEAKER_STOP_ARMED"',
            b'"sample_to_standby_us"',
        )
        forbidden = (
            check_resource_bench.PACK_PREFIX,
            b"LISTEN_NOW\0",
            b"QUESTION_ONLY_NOW\0",
            b"api.openai.com\0",
            b"K151_SPEAKER_V13",
        )
        if (
            len(observed) != 1
            or not all(marker in app for marker in required + protocols[observed[0]])
            or any(marker in app for marker in forbidden)
        ):
            raise ValueError("Unexpected speaker STOP diagnostic image")
        return {
            **envelope,
            **validate_slot(partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"]),
            "kind": "SYNTHETIC_SPEAKER_SCREEN_STOP_NOT_OPERATIONAL",
            "expected_protocol": observed[0],
            "local_nonce_start_required": True,
            "combined_start_window_ms": 10_000,
            "tone_samples": 60_000,
            "tone_peak_pcm16": 4096,
            "sample_rate_hz": 24_000,
            "microphone_enabled": False,
            "cloud_enabled": False,
            "electrical_stop_mute_verified": False,
        }
    if speaker:
        envelope, _ = inspect_envelope(app, elf_sha256, b"k151_speaker_probe")
        protocols = {
            "K151_SPEAKER_V1": b"WAIT_SPEAKER_LOCAL_START\0",
            "K151_SPEAKER_V2": b"WAIT_SPEAKER_STARTUP_LOCAL_START\0",
            "K151_SPEAKER_V3": b"WAIT_SPEAKER_CLOCK_LOCAL_START\0",
            "K151_SPEAKER_V4": b"WAIT_SPEAKER_PROTECTION_LOCAL_START\0",
            "K151_SPEAKER_V5": b"WAIT_SPEAKER_VDD_LOCAL_START\0",
            "K151_SPEAKER_V6": b"WAIT_SPEAKER_STANDBY_UVLS_LOCAL_START\0",
            "K151_SPEAKER_V7": b"WAIT_SPEAKER_RESET_UVLS_LOCAL_START\0",
            "K151_SPEAKER_V8": b"WAIT_SPEAKER_VDD_FOLLOWUP_LOCAL_START\0",
            "K151_SPEAKER_V9": b"WAIT_SPEAKER_SETTLING_LOCAL_START\0",
            "K151_SPEAKER_V10": b"WAIT_SPEAKER_CLEANUP_LOCAL_START\0",
            "K151_SPEAKER_V11": b"WAIT_SPEAKER_STANDBY_CHECK_LOCAL_START\0",
            "K151_SPEAKER_V12": b"WAIT_SPEAKER_MUTE_SETTLE_LOCAL_START\0",
            "K151_SPEAKER_V13": b"WAIT_SPEAKER_AMP_OFF_LOCAL_START\0",
        }
        cleanup_protocols = {
            "K151_SPEAKER_V10",
            "K151_SPEAKER_V11",
            "K151_SPEAKER_V12",
            "K151_SPEAKER_V13",
        }
        settling_protocols = cleanup_protocols | {"K151_SPEAKER_V9"}
        compact_vdd_protocols = settling_protocols | {"K151_SPEAKER_V8"}
        reset_protocols = compact_vdd_protocols | {"K151_SPEAKER_V7"}
        standby_protocols = reset_protocols | {"K151_SPEAKER_V6"}
        legacy_vdd_protocols = {"K151_SPEAKER_V5", "K151_SPEAKER_V6", "K151_SPEAKER_V7"}
        protection_protocols = standby_protocols | {"K151_SPEAKER_V4", "K151_SPEAKER_V5"}
        clock_protocols = protection_protocols | {"K151_SPEAKER_V3"}
        observed = [
            protocol
            for protocol in protocols
            if any(protocol.encode() + suffix in app for suffix in (b"\0", b'"'))
        ]
        forbidden = (
            check_resource_bench.PACK_PREFIX,
            b"LISTEN_NOW\0",
            b"QUESTION_ONLY_NOW\0",
            b"api.openai.com\0",
        )
        if (
            len(observed) != 1
            or protocols[observed[0]] not in app
            or b"K151_SPEAKER_PROBE_NOT_OPERATIONAL\0" not in app
            or any(marker in app for marker in forbidden)
            or (observed[0] != "K151_SPEAKER_V1" and b'"startup_stage"' not in app)
            or (
                observed[0] in clock_protocols
                and (b'"clock_wait_exit"' not in app or b'"clock_wait_last"' not in app)
            )
            or (observed[0] in protection_protocols and b'"protection"' not in app)
            or (
                observed[0] in legacy_vdd_protocols
                and not all(
                    field in app
                    for field in (
                        b'"uvls_after_clock_us"',
                        b'"vdd_after_uvls_us"',
                        b'"startup_vdd"',
                        b'"startup_vdd_mv"',
                    )
                )
            )
            or (observed[0] in standby_protocols and b'"standby_uvls"' not in app)
            or (observed[0] in reset_protocols and b'"reset_uvls"' not in app)
            or (observed[0] in compact_vdd_protocols and b'"vdd"' not in app)
            or (observed[0] in settling_protocols and b'"settling_uvls"' not in app)
            or (observed[0] in cleanup_protocols and b'"end"' not in app)
        ):
            raise ValueError("Unexpected speaker diagnostic image")
        return {
            **envelope,
            **validate_slot(partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"]),
            "kind": "SYNTHETIC_SPEAKER_PROBE_NOT_OPERATIONAL",
            "expected_protocol": observed[0],
            "local_nonce_start_required": True,
            "combined_start_window_ms": 10000,
            "microphone_enabled": False,
            "cloud_enabled": False,
            "tone_samples": 6000,
            "tone_peak_pcm16": 4096,
            "sample_rate_hz": 24000,
            "amplifier_or_fifo_drain_verified": False,
        }
    if silent_tx:
        envelope, _ = inspect_envelope(app, elf_sha256, b"k151_silent_tx_probe")
        if (
            check_resource_bench.PACK_PREFIX in app
            or b"LISTEN_NOW\0" in app
            or b"QUESTION_ONLY_NOW\0" in app
            or b"WAIT_SILENT_TX_LOCAL_START\0" not in app
            or b"K151_SILENT_TX_V1" not in app
        ):
            raise ValueError("Unexpected silent TX diagnostic image")
        return {
            **envelope,
            **validate_slot(partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"]),
            "kind": "GPIO_ISOLATED_SILENT_TX_NOT_OPERATIONAL",
            "local_nonce_start_required": True,
            "routes_audio_pins": False,
            "tx_observation_us": 100000,
            "tx_descriptor_count": 2,
            "tx_descriptor_frames": 240,
            "amplifier_or_fifo_drain_verified": False,
        }
    if question_only:
        envelope, _ = inspect_envelope(app, elf_sha256, b"k151_question_only")
        if (
            check_resource_bench.PACK_PREFIX in app
            or b"LISTEN_NOW\0" in app
            or b"MIC_WAKE_TRIAL_V" in app
            or b"QUESTION_ONLY_NOW\0" not in app
            or b"MIC_QUESTION_ONLY_TRIAL_V1\0" not in app
        ):
            raise ValueError("Question-only app markers or absence of WakeNet rejected")
        return {
            **envelope,
            **validate_slot(partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"]),
            "kind": "RECEIVE_ONLY_QUESTION_ONLY_NOT_OPERATIONAL",
            "local_nonce_start_required": True,
            "wake_model_bundled": False,
            "usb_exports_pcm": False,
            "question_capture_deadline_ms": 8000,
            "question_initial_quiet_ms": 500,
            "question_max_frames_20ms": 400,
            "combined_start_window_ms": 10000,
        }
    if wake_only_control:
        project = b"k151_wake_only_control"
    else:
        project = b"k151_mic_question_trial" if question else b"k151_mic_wake_trial"
    result = check_resource_bench.inspect_model_image(app, elf_sha256, project)
    manifest = {
        **result,
        **validate_slot(partition_csv, SLOT_OFFSET, result["erase_span_bytes"]),
        "kind": "RECEIVE_ONLY_MIC_WAKE_TRIAL_NOT_OPERATIONAL",
        "capture_deadline_ms": 5000,
        "max_frames_10ms": 500,
        "local_nonce_start_required": True,
        "usb_exports_pcm": False,
    }
    if question or wake_only_control:
        manifest.update(
            kind="RECEIVE_ONLY_MIC_QUESTION_TRIAL_NOT_OPERATIONAL",
            question_capture_deadline_ms=8000,
            question_initial_quiet_ms=500,
            question_max_frames_20ms=400,
            combined_start_window_ms=10000,
        )
    if wake_only_control:
        manifest.update(
            kind="RECEIVE_ONLY_WAKE_ONLY_CONTROL_NOT_OPERATIONAL",
            observation_frames_20ms=75,
            observation_pcm_ms=1500,
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--bin", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--partition-csv", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--question", action="store_true")
    mode.add_argument("--wake-only-control", action="store_true")
    mode.add_argument("--question-only", action="store_true")
    mode.add_argument("--silent-tx", action="store_true")
    mode.add_argument("--speaker", action="store_true")
    mode.add_argument("--speaker-stop", action="store_true")
    args = parser.parse_args()
    validate_source_head(args.source_head)
    build = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(
        args.bin.read_bytes(),
        build["elf"]["sha256"],
        args.partition_csv.read_text(encoding="utf-8"),
        question=args.question,
        wake_only_control=args.wake_only_control,
        question_only=args.question_only,
        silent_tx=args.silent_tx,
        speaker=args.speaker,
        speaker_stop=args.speaker_stop,
    )
    result.update(
        idf_commit=build["idf_commit"],
        elf=build["elf"],
        source_head=bind_source_head(result["app_version"], args.source_head),
    )
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

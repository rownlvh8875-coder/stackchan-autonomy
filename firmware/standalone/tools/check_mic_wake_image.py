"""Validate one receive-only K151 review artifact without opening a device."""

import argparse
import json
from pathlib import Path

from check_board_probe import validate_slot
from check_idf_build import validate
from check_resource_bench import inspect_model_image
from esp_app_image import SLOT_OFFSET, bind_source_head, validate_source_head


def inspect_image(app: bytes, elf_sha256: str, partition_csv: str, *, question=False) -> dict:
    project = b"k151_mic_question_trial" if question else b"k151_mic_wake_trial"
    result = inspect_model_image(app, elf_sha256, project)
    manifest = {
        **result,
        **validate_slot(partition_csv, SLOT_OFFSET, result["erase_span_bytes"]),
        "kind": "RECEIVE_ONLY_MIC_WAKE_TRIAL_NOT_OPERATIONAL",
        "capture_deadline_ms": 5000,
        "max_frames_10ms": 500,
        "local_nonce_start_required": True,
        "usb_exports_pcm": False,
    }
    if question:
        manifest.update(
            kind="RECEIVE_ONLY_MIC_QUESTION_TRIAL_NOT_OPERATIONAL",
            question_capture_deadline_ms=8000,
            question_initial_quiet_ms=500,
            question_max_frames_20ms=400,
            combined_start_window_ms=10000,
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
    parser.add_argument("--question", action="store_true")
    args = parser.parse_args()
    validate_source_head(args.source_head)
    build = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(
        args.bin.read_bytes(),
        build["elf"]["sha256"],
        args.partition_csv.read_text(encoding="utf-8"),
        question=args.question,
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

"""Validate a silent bench build for review. Never access or program a device."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from check_idf_build import validate
from esp_app_image import bind_source_head, inspect_envelope, validate_source_head
from prepare_wakenet_assets import MODEL_NAME, PACK_BYTES, PACK_SHA256

PACK_PREFIX = struct.pack("<I32sI", 1, MODEL_NAME.encode(), 3)
SLOT_OFFSET = 0x510000
SLOT_BYTES = 5_177_344


def inspect_model_image(app: bytes, elf_sha256: str, project: bytes) -> dict:
    envelope, regions = inspect_envelope(app, elf_sha256, project)
    start = app.find(PACK_PREFIX)
    if start < 0 or app.find(PACK_PREFIX, start + 1) >= 0:
        raise ValueError("missing or ambiguous embedded model")
    pack = app[start : start + PACK_BYTES]
    if len(pack) != PACK_BYTES or hashlib.sha256(pack).hexdigest() != PACK_SHA256:
        raise ValueError("embedded model integrity rejected")
    if not any(
        lo <= start
        and start + PACK_BYTES <= hi
        and 0x3C000000 <= address
        and address + hi - lo <= 0x3E000000
        for lo, hi, address in regions
    ):
        raise ValueError("embedded model is not in a DROM segment")
    return {
        **envelope,
        "model_bytes": PACK_BYTES,
        "model_sha256": PACK_SHA256,
        "model_in_readonly_app_segment": True,
    }


def inspect_image(app: bytes, elf_sha256: str) -> dict:
    return {
        "kind": "SILENT_RESOURCE_BENCH_NOT_OPERATIONAL",
        **inspect_model_image(app, elf_sha256, b"k151_resource_bench"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--bin", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    validate_source_head(args.source_head)
    base = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(args.bin.read_bytes(), base["elf"]["sha256"])
    result.update(
        idf_commit=base["idf_commit"],
        elf=base["elf"],
        source_head=bind_source_head(result["app_version"], args.source_head),
    )
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

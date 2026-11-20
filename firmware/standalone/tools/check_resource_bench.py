"""Validate a silent bench build for review. Never access or program a device."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from check_idf_build import validate
from prepare_wakenet_assets import MODEL_NAME, PACK_BYTES, PACK_SHA256

PACK_PREFIX = struct.pack("<I32sI", 1, MODEL_NAME.encode(), 3)
SLOT_OFFSET = 0x510000
SLOT_BYTES = 5_177_344


def inspect_image(app: bytes, elf_sha256: str) -> dict:
    if not 24 < len(app) <= SLOT_BYTES:
        raise ValueError("image size outside observed slot")
    if app[0] != 0xE9 or not 1 <= app[1] <= 16 or app[23] != 1:
        raise ValueError("not a hash-appended ESP app image")
    if struct.unpack_from("<H", app, 12)[0] != 9:
        raise ValueError("not ESP32-S3")
    minimum = struct.unpack_from("<H", app, 15)[0]
    maximum = struct.unpack_from("<H", app, 17)[0]
    if minimum > 2 or (maximum != 0xFFFF and maximum < 2):
        raise ValueError("image excludes observed chip revision v0.2")
    cursor, checksum = 24, 0xEF
    regions = []
    for _ in range(app[1]):
        if cursor + 8 > len(app):
            raise ValueError("truncated segment header")
        address, size = struct.unpack_from("<II", app, cursor)
        cursor += 8
        if size > len(app) - cursor or address + size > 0x100000000:
            raise ValueError("truncated or overflowing segment")
        regions.append((cursor, cursor + size, address))
        for byte in app[cursor : cursor + size]:
            checksum ^= byte
        cursor += size
    checksum_at = (cursor // 16 + 1) * 16 - 1
    if checksum_at + 33 != len(app) or app[checksum_at] != checksum:
        raise ValueError("image checksum/length rejected")
    if hashlib.sha256(app[: checksum_at + 1]).digest() != app[checksum_at + 1 :]:
        raise ValueError("image SHA rejected")
    first = regions[0][0]
    if (
        regions[0][1] - first < 256
        or struct.unpack_from("<I", app, first)[0] != 0xABCD5432
        or app[first + 48 : first + 80].split(b"\0", 1)[0] != b"k151_resource_bench"
    ):
        raise ValueError("not the dedicated bench app")
    embedded_elf_sha = app[first + 144 : first + 176].hex()
    if embedded_elf_sha != elf_sha256:
        raise ValueError("ELF does not match app descriptor")
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
        "kind": "SILENT_RESOURCE_BENCH_NOT_OPERATIONAL",
        "image_sha256": hashlib.sha256(app).hexdigest(),
        "elf_sha256_bound_to_image": embedded_elf_sha,
        "write_offset": SLOT_OFFSET,
        "write_bytes": len(app),
        "erase_span_bytes": (len(app) + 4095) // 4096 * 4096,
        "slot_bytes": SLOT_BYTES,
        "slot_occupied_by_factory_app": True,
        "active_or_spare_slot_proven": False,
        "model_bytes": PACK_BYTES,
        "model_sha256": PACK_SHA256,
        "model_in_readonly_app_segment": True,
        "partition_table_changed": False,
        "nvs_otadata_assets_changed": False,
        "install_authorized": False,
        "operating_admission": False,
        "physical_boot_inference_or_tls_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--bin", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    base = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(args.bin.read_bytes(), base["elf"]["sha256"])
    result.update(idf_commit=base["idf_commit"], elf=base["elf"], source_head=args.source_head)
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Review a published ESPHome K151 image pair and rehearse factory recovery in RAM."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from esp_app_image import (
    NVS_BYTES,
    NVS_OFFSET,
    PARTITION_TABLE_BYTES,
    PARTITION_TABLE_OFFSET,
    SLOT_BYTES,
    SLOT_OFFSET,
    inspect_envelope,
)
from offline_factory_recovery import (
    EXPECTED_PARTITIONS,
    IMAGE_BYTES,
    Rejected,
    _verified_factory,
    inspect_image,
)

# Published M5Stack release sizes and SHA-256 digests for the merged and app assets.
RELEASES = {
    "2026.3.0": (
        (5126528, "25e16c82b0a239f3becf6bcc98e81790ff9168bf407651ca6c9d805c19bfbc53"),
        (5060992, "3ecf89cecc63e64782f0beb4046183ffceae753767df182a6c8495510b79cfc0"),
    ),
    "2026.11.0": (
        (3293584, "a4488b77b9e75d740efcae6c7a50a59af90fe513089f9a53f110c4fd711c2924"),
        (3228048, "ec2cbadee1144d1897f7989a1c0ffa51e5c52d337015c3e978aefcf22a0eba69"),
    ),
}
SECTOR_BYTES = 0x1000
ALTERNATE_LAYOUT = {
    (1, 0): (0x9000, 0x2000),
    (1, 1): (0xB000, 0x1000),
    (0, 16): (0x10000, 0x7C0000),
    (0, 17): (0x7D0000, 0x7C0000),
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def read_published(path: Path, size: int, digest: str) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(size + 1)
    if len(data) != size or sha256(data) != digest:
        raise Rejected
    return data


def reference_layout(merged: bytes, app: bytes) -> tuple[int, int, int]:
    if merged[0] != 0xE9 or struct.unpack_from("<H", merged, 12)[0] != 9:
        raise Rejected
    # The pinned published app digest is the independent identity. Reuse the
    # structure/checksum parser without treating the embedded ELF hash as verified.
    inspect_envelope(app, app[24 + 8 + 144 : 24 + 8 + 176].hex(), b"stackchan-voice")
    padded = merged.ljust(IMAGE_BYTES, b"\xff")
    partitions = inspect_image(padded, sha256(padded))["partitions"]
    geometry = {
        (part["type"], part["subtype"]): (int(part["offset_hex"], 16), part["size_bytes"])
        for part in partitions
    }
    nvs_offset, nvs_size = geometry.pop((1, 2), (0, 0))
    if (
        len(partitions) != len(ALTERNATE_LAYOUT) + 1
        or geometry != ALTERNATE_LAYOUT
        or nvs_offset != 0xF90000
        or nvs_size < SECTOR_BYTES
    ):
        raise Rejected
    app_offset, app_slot_size = geometry[0, 16]
    if len(app) > app_slot_size or len(merged) != app_offset + len(app) or not merged.endswith(app):
        raise Rejected
    return app_offset, nvs_offset, nvs_size


def model_restore(original: bytes, merged: bytes, erase_bytes: int, nvs_offset: int) -> dict:
    def apply(data: bytes) -> bytearray:
        flash = bytearray(original)
        flash[:erase_bytes] = data.ljust(erase_bytes, b"\xff")
        return flash

    def restore_full(flash: bytearray) -> bool:
        flash[:] = original
        return flash == original

    partial_install = restore_full(apply(merged[: len(merged) // 2]))

    flash = apply(merged)
    table = slice(PARTITION_TABLE_OFFSET, PARTITION_TABLE_OFFSET + PARTITION_TABLE_BYTES)
    table_changes = flash[table] != original[table]

    previous_restore = flash.copy()
    for offset, size in ((SLOT_OFFSET, SLOT_BYTES), (NVS_OFFSET, NVS_BYTES)):
        previous_restore[offset : offset + size] = original[offset : offset + size]
    previous_matches = previous_restore == original

    # Model a write into the replacement layout after boot. Choose a changed
    # byte deterministically without parsing or producing any private settings.
    flash[nvs_offset] ^= 1
    interrupted_restore = flash.copy()
    interrupted_restore[:erase_bytes] = original[:erase_bytes]
    initial_span_matches = interrupted_restore == original

    return {
        "partition_table_changes": table_changes,
        "existing_ota1_nvs_restore_matches": previous_matches,
        "initial_range_restore_after_alternate_nvs_write_matches": initial_span_matches,
        "simulated_full_restore": {
            "partial_install": partial_install,
            "alternate_nvs_write": restore_full(flash),
            "interrupted_full_restore": restore_full(interrupted_restore),
        },
    }


def rehearse(
    factory_a: Path,
    factory_b: Path,
    factory_sha256: str,
    release: str,
    esphome_factory: Path,
    esphome_ota: Path,
) -> dict:
    merged_pin, ota_pin = RELEASES[release]
    merged = read_published(esphome_factory, *merged_pin)
    app = read_published(esphome_ota, *ota_pin)
    app_offset, nvs_offset, nvs_size = reference_layout(merged, app)
    original, factory = _verified_factory(factory_a, factory_b, factory_sha256)
    erase_bytes = (len(merged) + SECTOR_BYTES - 1) // SECTOR_BYTES * SECTOR_BYTES
    return {
        "status": "ESPHOME_TRANSITION_REHEARSED_IN_MEMORY",
        "release": release,
        "factory_backups_matched": factory["backup_count"],
        "candidate_write": {
            "offset": 0,
            "bytes": len(merged),
            "erase_bytes": erase_bytes,
            "sha256": merged_pin[1],
        },
        "esp32s3_app_offset": app_offset,
        "ota_app_sha256": ota_pin[1],
        "alternate_nvs": {"offset": nvs_offset, "bytes": nvs_size},
        "factory_partitions_overlapped": [
            name for name, offset, _, _, _ in EXPECTED_PARTITIONS if int(offset, 16) < erase_bytes
        ],
        "full_restore_range": {"offset": 0, "bytes": IMAGE_BYTES},
        **model_restore(original, merged, erase_bytes, nvs_offset),
        "physical_write_tested": False,
        "current_device_verified": False,
        "install_authorized": False,
        "restore_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("factory-a", "factory-b", "esphome-factory", "esphome-ota"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--release", required=True, choices=tuple(RELEASES))
    args = parser.parse_args(argv)
    try:
        report = rehearse(
            args.factory_a,
            args.factory_b,
            args.expected_sha256,
            args.release,
            args.esphome_factory,
            args.esphome_ota,
        )
    except (Rejected, OSError, ValueError, struct.error, MemoryError):
        print("ESPHOME_TRANSITION_REJECTED")
        return 2
    print(json.dumps(report, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

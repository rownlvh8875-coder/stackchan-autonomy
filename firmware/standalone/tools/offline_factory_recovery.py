"""Offline-only, two-copy K151 factory backup and partition-layout review.

This accepts user-local binary file paths but has no device/serial/network or
write API. A successful report is NOT installation or restore approval.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

from esp_app_image import (
    NVS_BYTES,
    NVS_OFFSET,
    OTADATA_BYTES,
    OTADATA_OFFSET,
    PARTITION_TABLE_BYTES,
    PARTITION_TABLE_OFFSET,
    SLOT_BYTES,
    SLOT_OFFSET,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
# Reuse the repository's already-tested, hash-pinned partition-table parser.
sys.path.insert(0, str(REPO_ROOT / "experiments" / "k151_layout_spike"))
from inspect_layout import IMAGE_BYTES, Rejected, inspect_image  # noqa: E402

# User-reported factory layout, NOT a newly inspected hardware fact.
EXPECTED_PARTITIONS = (
    ("nvs", "0x00009000", 16384, 1, 2),
    ("otadata", "0x0000d000", 8192, 1, 0),
    ("phy_init", "0x0000f000", 4096, 1, 1),
    ("ota_0", "0x00020000", 5177344, 0, 16),
    ("ota_1", "0x00510000", 5177344, 0, 17),
    ("assets", "0x00a00000", 4194304, 1, 130),
    ("coredump", "0x00e00000", 65536, 1, 3),
)


def inspect_otadata(region: bytes) -> dict:
    """Sanitized historical candidates, NOT the currently running or spare slot.

    Pinned IDF fff9895: esp_flash_partitions.h, bootloader_common_loader.c,
    bootloader_utility.c and otatool.py. Do not export the 20-byte seq_label.
    Factory bootloader config/image validation/fallback may change selection.
    """
    if len(region) != 8192:
        raise ValueError("invalid OTA region size")
    states = {
        0: "new",
        1: "pending_verify",
        2: "valid",
        3: "invalid",
        4: "aborted",
        0xFFFFFFFF: "undefined",
    }
    records = []
    for offset in (0, 4096):
        seq = struct.unpack_from("<I", region, offset)[0]
        state, crc = struct.unpack_from("<II", region, offset + 24)
        crc_valid = crc == binascii.crc32(region[offset : offset + 4], 0xFFFFFFFF)
        records.append(
            {
                "sequence": seq,
                "state": states.get(state, "unknown"),
                "crc_valid": crc_valid,
                "eligible": seq != 0xFFFFFFFF and crc_valid and state in (0, 1, 2, 0xFFFFFFFF),
            }
        )

    def select(rollback):
        choices = [
            i
            for i, r in enumerate(records)
            if r["eligible"] and not (rollback and r["state"] == "pending_verify")
        ]
        # IDF takes the numerically largest uint32 sequence; ties favor copy 0.
        selected = max(choices, key=lambda i: records[i]["sequence"]) if choices else None
        slot = (
            f"ota_{((records[selected]['sequence'] - 1) & 0xFFFFFFFF) % 2}"
            if selected is not None
            else None
        )
        return selected, slot

    selected, candidate = select(False)
    _, rollback_candidate = select(True)
    return {
        "records": records,
        "selected_record_without_rollback": selected,
        "without_rollback_candidate": candidate,
        "with_rollback_candidate": rollback_candidate,
        "factory_bootloader_policy_verified": False,
        "running_slot_verified": False,
        "spare_slot_verified": False,
        "evidence_scope": "HASH_VERIFIED_BACKUP_SNAPSHOT_ONLY",
    }


def verify_copies(path_a: Path, path_b: Path, expected_sha256: str) -> dict:
    if path_a.resolve() == path_b.resolve():
        raise Rejected
    images = []
    layouts = []
    for path in (path_a, path_b):
        if not path.is_file() or path.stat().st_size != IMAGE_BYTES:
            raise Rejected
        # The existing verifier checks all bytes, SHA256 and ESP-IDF partition MD5.
        image = path.read_bytes()
        report = inspect_image(image, expected_sha256)
        if report["partitions"] is None:
            raise Rejected
        parts = tuple(
            (
                part["label"],
                part["offset_hex"],
                part["size_bytes"],
                part["type"],
                part["subtype"],
            )
            for part in report["partitions"]
        )
        if parts != EXPECTED_PARTITIONS or report["app_partition_count"] != 2:
            raise Rejected
        images.append(image)
        layouts.append(parts)
    if images[0] != images[1] or layouts[0] != layouts[1]:
        raise Rejected
    return {
        "status": "TWO_LOCAL_BACKUPS_MATCH_NOT_INSTALL_AUTHORIZATION",
        "backup_count": 2,
        "image_length_bytes": IMAGE_BYTES,
        "sha256_verified_locally": hashlib.sha256(images[0]).hexdigest(),
        "factory_ota1_sha256": hashlib.sha256(
            images[0][SLOT_OFFSET : SLOT_OFFSET + SLOT_BYTES]
        ).hexdigest(),
        "factory_table_sha256": hashlib.sha256(
            images[0][PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + PARTITION_TABLE_BYTES]
        ).hexdigest(),
        "factory_otadata_sha256": hashlib.sha256(
            images[0][OTADATA_OFFSET : OTADATA_OFFSET + OTADATA_BYTES]
        ).hexdigest(),
        "partition_table_md5_checked": True,
        "partition_count": len(EXPECTED_PARTITIONS),
        "ota_partition_count": 2,
        "ota_slot_bytes": 5177344,
        "active_slot_identified": False,
        "ota_metadata": inspect_otadata(images[0][0xD000:0xF000]),
        "independent_offsite_copy_verified": False,
        "restore_write_tested": False,
        "factory_official_app_compatibility_verified": False,
        "install_authorized": False,
        "flash_modified": False,
    }


def verify_trial_restore(
    factory_a: Path, factory_b: Path, expected_sha256: str, ota1: Path, pretrial_nvs: Path
) -> dict:
    """Describe a complete paid-trial rollback using local files only."""
    factory = verify_copies(factory_a, factory_b, expected_sha256)
    with ota1.open("rb") as slot:
        ota1_bytes = slot.read(SLOT_BYTES + 1)
    if (
        len(ota1_bytes) != SLOT_BYTES
        or hashlib.sha256(ota1_bytes).hexdigest() != factory["factory_ota1_sha256"]
    ):
        raise ValueError("factory OTA1 restore slice disagrees with the verified full backups")
    with pretrial_nvs.open("rb") as snapshot:
        nvs_bytes = snapshot.read(NVS_BYTES + 1)
    if len(nvs_bytes) != NVS_BYTES:
        raise ValueError("pretrial NVS snapshot size rejected")
    return {
        "matching_factory_copies": factory["backup_count"],
        "factory_table_sha256": factory["factory_table_sha256"],
        "factory_otadata_sha256": factory["factory_otadata_sha256"],
        "restore_in_order": [
            {
                "partition": "ota_1",
                "offset": SLOT_OFFSET,
                "bytes": SLOT_BYTES,
                "sha256": factory["factory_ota1_sha256"],
            },
            {
                "partition": "nvs",
                "offset": NVS_OFFSET,
                "bytes": NVS_BYTES,
                "sha256": hashlib.sha256(nvs_bytes).hexdigest(),
            },
        ],
        "verify_each_range_before_next_restore": True,
        "pretrial_nvs_verified_against_device": False,
        "restore_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factory-a", required=True, type=Path)
    parser.add_argument("--factory-b", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        report = verify_copies(args.factory_a, args.factory_b, args.expected_sha256)
    except (Rejected, ValueError, OSError, MemoryError):
        print("FACTORY_BACKUP_REJECTED")
        return 2
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

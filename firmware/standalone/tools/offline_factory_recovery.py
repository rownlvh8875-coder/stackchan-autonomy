"""Offline-only, two-copy K151 factory backup and partition-layout review.

This accepts user-local binary file paths but has no device/serial/network or
write API. A successful report is NOT installation or restore approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

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
        "partition_table_md5_checked": True,
        "partition_count": len(EXPECTED_PARTITIONS),
        "ota_partition_count": 2,
        "ota_slot_bytes": 5177344,
        "active_slot_identified": False,
        "independent_offsite_copy_verified": False,
        "restore_write_tested": False,
        "factory_official_app_compatibility_verified": False,
        "install_authorized": False,
        "flash_modified": False,
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

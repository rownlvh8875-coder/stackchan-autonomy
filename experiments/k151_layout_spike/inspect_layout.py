"""Read-only development spike: inspect a hash-pinned local K151 backup, never a device."""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

IMAGE_BYTES = 0x1000000
TABLE_OFFSET = 0x8000
TABLE_BYTES = 0xC00
SECTOR_BYTES = 0x1000
ENTRY = struct.Struct("<2sBBII16sI")
MD5_PREFIX = b"\xeb\xeb" + b"\xff" * 14
PUBLIC_LABELS = {
    "nvs",
    "otadata",
    "phy_init",
    "factory",
    "ota_0",
    "ota_1",
    "assets",
    "coredump",
    "storage",
    "nvs_keys",
}


class Rejected(Exception):
    pass


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise Rejected from None


def inspect_image(image: bytes, expected_sha256: str) -> dict:
    if len(image) != IMAGE_BYTES or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise Rejected
    if hashlib.sha256(image).hexdigest() != expected_sha256.lower():
        raise Rejected

    table = image[TABLE_OFFSET : TABLE_OFFSET + TABLE_BYTES]
    partitions = []
    checksum_ok = False
    for offset in range(0, TABLE_BYTES, ENTRY.size):
        record = table[offset : offset + ENTRY.size]
        if record.startswith(MD5_PREFIX):
            # ESP-IDF's table-format checksum, not an authentication mechanism.
            checksum = hashlib.md5(table[:offset], usedforsecurity=False).digest()
            if record[16:] != checksum or table[offset + 32 :] != b"\xff" * (
                TABLE_BYTES - offset - 32
            ):
                raise Rejected
            checksum_ok = True
            break
        magic, kind, subtype, start, size, raw_label, flags = ENTRY.unpack(record)
        if magic != b"\xaa\x50" or flags & ~3:
            raise Rejected
        if (
            not size
            or start < TABLE_OFFSET + SECTOR_BYTES
            or start % SECTOR_BYTES
            or size % SECTOR_BYTES
            or start + size > IMAGE_BYTES
            or (kind == 0 and start % 0x10000)
        ):
            raise Rejected
        label = raw_label.split(b"\0", 1)[0].decode("ascii", errors="replace")
        partitions.append(
            {
                "label": label if label in PUBLIC_LABELS else "REDACTED_NONSTANDARD_LABEL",
                "type": kind,
                "subtype": subtype,
                "offset_hex": f"0x{start:08x}",
                "size_bytes": size,
                "flags": flags,
            }
        )
    if not checksum_ok or not partitions:
        raise Rejected
    ordered = sorted(partitions, key=lambda part: int(part["offset_hex"], 16))
    for left, right in zip(ordered, ordered[1:]):
        if int(left["offset_hex"], 16) + left["size_bytes"] > int(right["offset_hex"], 16):
            raise Rejected
    return {
        "status": "LAYOUT_ONLY_NOT_INSTALL_APPROVAL",
        "backup_bytes": len(image),
        "backup_sha256_matches_expected": True,
        "table_offset_hex": f"0x{TABLE_OFFSET:08x}",
        "table_md5_verified": True,
        "partitions": partitions,
        "app_partition_count": sum(part["type"] == 0 for part in partitions),
        "active_app_slot": "NOT_DETERMINED",
        "spare_slot_verified": False,
        "installation_safe": False,
    }


def main(argv=None) -> int:
    parser = PrivateParser(description=__doc__)
    parser.add_argument("backup")
    parser.add_argument("--expected-sha256", required=True)
    try:
        args = parser.parse_args(argv)
        path = Path(args.backup)
        if not path.is_file() or path.stat().st_size != IMAGE_BYTES:
            raise Rejected
        with path.open("rb") as stream:
            image = stream.read(IMAGE_BYTES + 1)
        report = inspect_image(image, args.expected_sha256)
    except (Rejected, OSError, ValueError, struct.error):
        print("LAYOUT_INPUT_REJECTED")
        return 2
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

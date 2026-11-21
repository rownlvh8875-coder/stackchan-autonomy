"""Common ESP32-S3 diagnostic envelope and checkout/ELF binding, no device I/O."""

import hashlib
import re
import struct

SLOT_OFFSET = 0x510000
SLOT_BYTES = 5_177_344


def validate_source_head(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("missing or invalid actual checkout commit")
    return value


def bind_source_head(app_version: str, source_head: str) -> str:
    source_head = validate_source_head(source_head)
    if app_version != source_head[:12]:
        raise ValueError("app version does not bind actual checkout commit")
    return source_head


def inspect_envelope(app: bytes, elf_sha256: str, project: bytes) -> tuple[dict, list]:
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
        or app[first + 48 : first + 80].split(b"\0", 1)[0] != project
    ):
        raise ValueError("unexpected diagnostic app project")
    embedded_elf_sha = app[first + 144 : first + 176].hex()
    if embedded_elf_sha != elf_sha256:
        raise ValueError("ELF does not match app descriptor")
    return {
        "app_version": app[first + 16 : first + 48].split(b"\0", 1)[0].decode("ascii"),
        "image_sha256": hashlib.sha256(app).hexdigest(),
        "elf_sha256_bound_to_image": embedded_elf_sha,
        "write_offset": SLOT_OFFSET,
        "write_bytes": len(app),
        "erase_span_bytes": (len(app) + 4095) // 4096 * 4096,
        "slot_bytes": SLOT_BYTES,
        "slot_occupied_by_factory_app": True,
        "active_or_spare_slot_proven": False,
        "partition_table_changed": False,
        "nvs_otadata_assets_changed": False,
        "install_authorized": False,
        "operating_admission": False,
        "physical_boot_inference_or_tls_validated": False,
    }, regions

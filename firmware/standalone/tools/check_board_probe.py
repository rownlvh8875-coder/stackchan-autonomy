"""Validate a separate board or panel probe for review; never access a device."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from check_idf_build import validate
from esp_app_image import (
    SLOT_BYTES,
    SLOT_OFFSET,
    bind_source_head,
    inspect_envelope,
    validate_source_head,
)


def validate_slot(partition_csv: str, write_offset: int, erase_bytes: int) -> dict:
    """CSV decoded by pinned IDF gen_esp32part from the *built binary* table.

    This checks build/bundle scope, not the current device's table or OTA state.
    """

    def number(value):
        value = value.strip().lower()
        multiplier = {"k": 1024, "m": 1024 * 1024}.get(value[-1:], 1)
        return int(value[:-1] if multiplier != 1 else value, 0) * multiplier

    records = []
    for row in csv.reader(io.StringIO(partition_csv)):
        if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
            continue
        if len(row) != 6:
            raise ValueError("invalid built partition record")
        name, kind, subtype, offset, size, flags = [v.strip() for v in row]
        offset, size = number(offset), number(size)
        if not size or offset < 0x9000 or offset % 4096 or size % 4096 or offset + size > 0x1000000:
            raise ValueError("built partition outside observed geometry")
        records.append((offset, size, name, kind, subtype, flags))
    records.sort()
    for left, right in zip(records, records[1:]):
        if left[0] + left[1] > right[0]:
            raise ValueError("overlapping built partitions")
    selected = [record for record in records if record[0] == write_offset]
    if write_offset != SLOT_OFFSET or len(selected) != 1:
        raise ValueError("selected write offset is not reviewed slot1")
    offset, size, name, kind, subtype, flags = selected[0]
    if (
        name != "ota_1"
        or kind != "app"
        or subtype != "ota_1"
        or size != SLOT_BYTES
        or flags
        or not 0 < erase_bytes <= size
    ):
        raise ValueError("built OTA subtype/size/flags or erase range rejected")
    return {
        "selected_partition": "ota_1",
        "selected_partition_type": 0,
        "selected_partition_subtype": 17,
        "build_partition_csv_sha256": hashlib.sha256(partition_csv.encode()).hexdigest(),
        "selected_write_matches_build_slot": True,
        "current_device_table_verified": False,
    }


def inspect_image(
    app: bytes, elf_sha256: str, *, write_offset: int, partition_csv: str, panel: bool = False
) -> dict:
    project = b"k151_panel_probe" if panel else b"k151_board_probe"
    envelope, _ = inspect_envelope(app, elf_sha256, project)
    scope = (
        {
            "kind": "PANEL_HEAD_STOP_PROBE_NOT_OPERATIONAL",
            "device_configuration_writes": True,
            "volatile_scope": "LCD and backlight, FT6336U and Si12T, AW9523B IRQ and GPIO21",
            "physical_panel_head_stop_verified": False,
            "accepts_credentials": False,
            "paid_api_called": False,
            "maximum_trial_ms": 10000,
        }
        if panel
        else {
            "kind": "READONLY_BOARD_PROBE_NOT_OPERATIONAL",
            "device_configuration_writes": False,
            "hardware_readback_validated": False,
        }
    )
    return {
        **envelope,
        **validate_slot(partition_csv, write_offset, envelope["erase_span_bytes"]),
        **scope,
        "gpio_mux_changes_after_start": True,
        "power_mute_or_audio_readiness_proven": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--bin", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--write-offset", required=True, type=lambda v: int(v, 0))
    parser.add_argument("--partition-csv", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--panel", action="store_true")
    args = parser.parse_args()
    validate_source_head(args.source_head)
    base = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(
        args.bin.read_bytes(),
        base["elf"]["sha256"],
        write_offset=args.write_offset,
        partition_csv=args.partition_csv.read_text(encoding="utf-8"),
        panel=args.panel,
    )
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

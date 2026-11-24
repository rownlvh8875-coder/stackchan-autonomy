"""Validate a separate board or panel probe for review; never access a device."""

import argparse
import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path

from check_idf_build import validate
from esp_app_image import (
    SLOT_BYTES,
    SLOT_OFFSET,
    bind_source_head,
    inspect_envelope,
    validate_source_head,
)


def validate_slot(
    partition_csv: str, write_offset: int, erase_bytes: int, *, require_nvs: bool = False
) -> dict:
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
    if require_nvs and (0x9000, 0x4000, "nvs", "data", "nvs", "") not in records:
        raise ValueError("built NVS size/offset/flags rejected")
    return {
        "selected_partition": "ota_1",
        "selected_partition_type": 0,
        "selected_partition_subtype": 17,
        "build_partition_csv_sha256": hashlib.sha256(partition_csv.encode()).hexdigest(),
        "selected_write_matches_build_slot": True,
        "current_device_table_verified": False,
    }


def inspect_image(
    app: bytes,
    elf_sha256: str,
    *,
    write_offset: int,
    partition_csv: str,
    panel: bool = False,
    screen_stop_only: bool = False,
    power_readback: bool = False,
) -> dict:
    project = b"k151_panel_probe" if panel else b"k151_board_probe"
    if screen_stop_only:
        project = b"k151_screen_stop_probe"
    if power_readback:
        project = b"k151_power_readback"
    envelope, _ = inspect_envelope(app, elf_sha256, project)
    if screen_stop_only and b"K151_PANEL_SCREEN_STOP_PROBE_NOT_OPERATIONAL\x00" not in app:
        raise ValueError("STOP-only diagnostic protocol marker absent")
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
        if panel or screen_stop_only
        else {
            "kind": "READONLY_BOARD_PROBE_NOT_OPERATIONAL",
            "device_configuration_writes": False,
            "hardware_readback_validated": False,
        }
    )
    if screen_stop_only:
        scope.update(
            kind="PANEL_SCREEN_STOP_PROBE_NOT_OPERATIONAL",
            volatile_scope="LCD and backlight, FT6336U, AW9523B IRQ and GPIO21",
            head_sensor_in_trial=False,
            physical_screen_stop_verified=False,
        )
    if power_readback:
        if not all(
            marker in app
            for marker in (
                b"K151_POWER_READBACK_NOT_OPERATIONAL\0",
                b"WAIT_POWER_LOCAL_START\0",
                b"K151_POWER_READBACK_V1",
            )
        ):
            raise ValueError("Power-only diagnostic protocol markers absent")
        scope.update(
            kind="READONLY_POWER_READBACK_NOT_OPERATIONAL",
            expected_protocol="K151_POWER_READBACK_V1",
        )
    return {
        **envelope,
        **validate_slot(partition_csv, write_offset, envelope["erase_span_bytes"]),
        **scope,
        "gpio_mux_changes_after_start": True,
        "power_mute_or_audio_readiness_proven": False,
    }


def verify_panel_symbols(
    nm_listing: str, *, screen_stop_only: bool = False, power_readback: bool = False
) -> None:
    symbols = {line.split()[-1] for line in nm_listing.splitlines() if line.split()}
    if "app_main" not in symbols:
        raise ValueError("missing diagnostic app_main in ELF symbol table")
    prefixes = (
        "i2s_",
        "esp_codec_dev_",
        "es7210_",
        "aw88298_",
        "esp_wifi_",
        "esp_http_client_",
        "nvs_flash_",
        "esp_partition_write",
        "esp_partition_erase",
        "esp_ota_set_boot_partition",
    )
    if any(name.startswith(prefixes) for name in symbols):
        raise ValueError("unexpected operational symbol in panel probe ELF")
    if screen_stop_only and any("K151HeadTouchOwner" in name for name in symbols):
        raise ValueError("unexpected head sensor symbol in STOP-only probe ELF")
    if power_readback and symbols & {"i2c_master_transmit", "i2c_master_multi_buffer_transmit"}:
        raise ValueError("unexpected configuration write symbol in power readback ELF")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--bin", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--write-offset", required=True, type=lambda v: int(v, 0))
    parser.add_argument("--partition-csv", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--panel", action="store_true")
    mode.add_argument("--screen-stop-only", action="store_true")
    mode.add_argument("--power-readback", action="store_true")
    parser.add_argument("--nm", help="Pinned Xtensa nm for panel and power diagnostics")
    args = parser.parse_args()
    inspect_symbols = args.panel or args.screen_stop_only or args.power_readback
    if inspect_symbols and not args.nm:
        parser.error("panel and power diagnostics require --nm to check the linked ELF")
    validate_source_head(args.source_head)
    base = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(
        args.bin.read_bytes(),
        base["elf"]["sha256"],
        write_offset=args.write_offset,
        partition_csv=args.partition_csv.read_text(encoding="utf-8"),
        panel=args.panel,
        screen_stop_only=args.screen_stop_only,
        power_readback=args.power_readback,
    )
    result.update(
        idf_commit=base["idf_commit"],
        elf=base["elf"],
        source_head=bind_source_head(result["app_version"], args.source_head),
    )
    if inspect_symbols:
        symbols = subprocess.run(
            [args.nm, "--defined-only", str(args.elf)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        verify_panel_symbols(
            symbols.stdout,
            screen_stop_only=args.screen_stop_only,
            power_readback=args.power_readback,
        )
        result["no_operational_symbols_verified"] = True
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

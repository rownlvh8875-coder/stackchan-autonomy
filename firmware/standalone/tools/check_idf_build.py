"""Check one compiled Xtensa ESP32-S3 APP artifact; never program a device.

This checks the ELF machine header, measured app size against the observed
K151 OTA slot, and records source/IDF/build SHA-256 hashes. It does not prove
hardware routing, the active OTA slot or flash/restore compatibility.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

OBSERVED_K151_OTA_SLOT = 5_177_344
EXPECTED_IDF_SHA = "fff9895c82d744c7237be8847347bdd1b07c6643"


def metadata(path: Path) -> dict[str, int | str]:
    return {"size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_realtime_transport(app: bytes) -> None:
    if b"/v1/realtime?model=gpt-realtime-2.1-mini" not in app:
        raise ValueError("missing linked Realtime synthesis path")
    if any(message in app for message in (b"Error write Upgrade header", b"Write upgrade request")):
        raise ValueError("WebSocket upgrade diagnostics can expose the credential")


def validate(elf: Path, app: Path, idf_head: str) -> dict:
    if idf_head != EXPECTED_IDF_SHA:
        raise ValueError("ESP-IDF is not the pinned v6.1 commit")
    header = elf.read_bytes()[:64]
    if len(header) < 52 or header[:4] != b"\x7fELF":
        raise ValueError("missing or truncated ELF header")
    if header[4] != 1 or header[5] != 1 or header[6] != 1:
        raise ValueError("expected ELF32 little-endian version 1")
    machine = struct.unpack_from("<H", header, 18)[0]
    if machine != 94:  # EM_XTENSA
        raise ValueError(f"expected Xtensa ELF (EM_XTENSA=94), got {machine}")
    app_info = metadata(app)
    if app_info["size"] == 0 or app_info["size"] > OBSERVED_K151_OTA_SLOT:
        raise ValueError("app binary outside confirmed single-slot size")
    return {
        "status": "COMPILED_NOT_APPROVED_FOR_DEVICE_INSTALLATION",
        "target": "esp32s3",
        "elf_machine": machine,
        "idf_commit": idf_head,
        "app_slot_size_limit": OBSERVED_K151_OTA_SLOT,
        "elf": metadata(elf),
        "app": app_info,
        "installed": False,
        "hardware_accessed": False,
        "paid_api_called": False,
        "factory_bootloader_or_partition_compatibility": "NOT_VALIDATED",
        "hardware_audio_lcd_usb_wifi_tls": "NOT_IMPLEMENTED",
        "note": "Do not flash; app SHA/size only, no factory recovery proof",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check-realtime", action="store_true")
    args = parser.parse_args()
    result = validate(args.elf, args.bin, args.idf_head)
    if args.check_realtime:
        verify_realtime_transport(args.bin.read_bytes())
        result["realtime_fixed_host_and_safe_upgrade_logging"] = "LINKED_NO_CREDENTIAL_LOGS"
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

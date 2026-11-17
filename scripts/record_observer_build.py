"""Record input/output hashes of a real Xtensa build; never install or read a device."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def require(condition):
    if not condition:
        raise SystemExit("OBSERVER_BUILD_INPUT_REJECTED")


def record(upstream, idf, output):
    upstream, idf = (Path(upstream).resolve(), Path(idf).resolve())
    pins = json.loads((ROOT / "firmware/observer/dependencies.json").read_text())

    def head(path):
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()

    require(head(upstream) == pins["upstream"] and head(idf) == pins["esp_idf"])
    firmware = upstream / "firmware"
    for repo in pins["repos"]:
        require(head(firmware / repo["path"]) == repo["commit"])
    config = (firmware / "sdkconfig").read_text()
    for required in (
        "CONFIG_STACKCHAN_PC_OBSERVER=y",
        "CONFIG_ESP_CONSOLE_UART_DEFAULT=y",
        "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y",
        'CONFIG_IDF_TARGET="esp32s3"',
        "CONFIG_LOG_MAXIMUM_LEVEL=3",
    ):
        require(required in config.splitlines())
    inputs = {}
    for folder in ("core", "esp"):
        for path in sorted((ROOT / "firmware/observer" / folder).glob("*")):
            require(
                path.read_bytes()
                == (firmware / "main/hal/pc_observer" / folder / path.name).read_bytes()
            )
            inputs[str(path.relative_to(ROOT))] = digest(path)
    inputs["integration.patch"] = digest(ROOT / "firmware/observer/integration.patch")
    inputs["camera-access.patch"] = digest(ROOT / "firmware/observer/camera-access.patch")
    inputs["patched-esp-video-header"] = digest(
        firmware / "xiaozhi-esp32/main/boards/common/esp_video.h"
    )
    inputs["managed-dependencies.lock"] = digest(firmware / "dependencies.lock")
    inputs["sdkconfig"] = digest(firmware / "sdkconfig")
    build = firmware / "build"
    commands = json.loads((build / "compile_commands.json").read_text())
    sources = [Path(c["file"]).name for c in commands if "/pc_observer/" in c["file"]]
    require(set(sources) == {"observer_core.cpp", "observer_usb.cpp"})
    elf = (build / "stack-chan.elf").read_bytes()
    require(elf[:6] == b"\x7fELF\x01\x01" and int.from_bytes(elf[18:20], "little") == 94)
    outputs = {
        name: digest(build / name)
        for name in (
            "stack-chan.elf",
            "stack-chan.bin",
            "bootloader/bootloader.bin",
            "partition_table/partition-table.bin",
            "generated_assets.bin",
            "ota_data_initial.bin",
        )
    }
    manifest = {
        "date": "2026-11-17",
        "status": "COMPILED_NOT_APPROVED_FOR_DEVICE_INSTALLATION",
        "target": "esp32s3",
        "elf_machine": "Xtensa (94)",
        "pins": pins,
        "command": "idf.py -C <prepared-upstream>/firmware build",
        "configuration": {
            "board": "M5STACK_STACK_CHAN",
            "observer": True,
            "console": "UART0",
            "usb_secondary_console": False,
            "log_maximum_level": 3,
            "production_authentication": False,
        },
        "compiled_observer_sources": sources,
        "inputs": inputs,
        "outputs": outputs,
        "hardware_accessed": False,
        "paid_api_called": False,
        "installed": False,
        "pending": [
            "LCD/USB routing",
            "backup and verified restore",
            "service authentication",
            "camera driver timing/recovery",
            "real sensors/vision/voice coexistence",
            "separate exact-image installation approval",
        ],
    }
    Path(output).write_text(json.dumps(manifest, indent=2) + "\n")
    (build / "NOT_APPROVED_FOR_INSTALLATION.txt").write_text(
        "Prototype source build only. No device installation authorized.\nUnresolved service auth, board/LCD/USB routing, backup/restore and driver recovery.\n"
    )
    print("OBSERVER_XTENSA_BUILD_RECORDED_INSTALLATION_HOLD")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream")
    parser.add_argument("--idf", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    record(args.upstream, args.idf, args.output)

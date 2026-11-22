"""Bind an unarmed K151 conversation review to its ELF, model and slot geometry."""

import argparse
import json
from pathlib import Path

from check_board_probe import validate_slot
from check_idf_build import validate, verify_realtime_transport
from check_resource_bench import inspect_model_image
from esp_app_image import SLOT_OFFSET, bind_source_head, validate_source_head


def verify_sdkconfig(text: str) -> None:
    expected = {
        "CONFIG_SPIRAM": "y",
        "CONFIG_SPIRAM_MODE_QUAD": "y",
        "CONFIG_SPIRAM_SPEED_80M": "y",
        "CONFIG_SPIRAM_USE_MALLOC": "y",
        "CONFIG_FREERTOS_HZ": "1000",
        "CONFIG_ESP_MAIN_TASK_AFFINITY_CPU0": "y",
        "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "12288",
        "CONFIG_ESP_CONSOLE_UART_DEFAULT": "y",
        "CONFIG_ESP_CONSOLE_SECONDARY_NONE": "y",
        "CONFIG_ESP_COREDUMP_ENABLE_TO_NONE": "y",
    }
    values = dict(line.split("=", 1) for line in text.splitlines() if line.startswith("CONFIG_"))
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValueError(f"conversation build requires {key}")


def inspect_image(app: bytes, elf_sha256: str, partition_csv: str) -> dict:
    envelope = inspect_model_image(app, elf_sha256, b"k151_conversation_review")
    markers = (
        # ESP_LOGW wraps this marker in its format string, including a newline.
        b"K151_CONVERSATION_REVIEW_NO_RELEASE",
        b"Say Hi StackChan\0",
        b"Standby verified. Trial ended.\0",
    )
    if b"K151_CONVERSATION_LOCAL_RELEASE" in app:
        raise ValueError("private release marker in public conversation image")
    for marker in markers:
        if marker not in app:
            raise ValueError(f"missing expected conversation marker {marker!r}")
    verify_realtime_transport(app)
    return {
        **envelope,
        **validate_slot(partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"]),
        "kind": "CONVERSATION_REVIEW_NO_RELEASE",
        "private_board_policy_embedded": False,
        "cloud_enabled_at_boot": False,
        "paid_api_called": False,
        "physical_output_or_stop_proven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("elf", "bin", "partition-csv", "sdkconfig", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    args = parser.parse_args()
    validate_source_head(args.source_head)
    verify_sdkconfig(args.sdkconfig.read_text(encoding="utf-8"))
    base = validate(args.elf, args.bin, args.idf_head)
    result = inspect_image(
        args.bin.read_bytes(), base["elf"]["sha256"], args.partition_csv.read_text(encoding="utf-8")
    )
    result.update(
        idf_commit=base["idf_commit"],
        elf=base["elf"],
        source_head=bind_source_head(result["app_version"], args.source_head),
        psram_console_and_task_config_verified=True,
    )
    with args.out.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

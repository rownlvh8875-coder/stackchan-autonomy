"""Bind a K151 conversation image and, locally, a one-turn restore review."""

import argparse
import json
import os
from pathlib import Path

from check_board_probe import validate_slot
from check_idf_build import validate, verify_realtime_transport
from check_resource_bench import inspect_model_image
from esp_app_image import SLOT_OFFSET, bind_source_head, validate_source_head
from offline_factory_recovery import Rejected, verify_trial_restore

PUBLIC_MARKER = b"K151_CONVERSATION_REVIEW_NO_RELEASE"
PRIVATE_MARKER = b"K151_CONVERSATION_LOCAL_RELEASE"
ONE_TURN_MARKER = PRIVATE_MARKER + b"_ONE_PAID_TURN\0"
DEVICE_OBSERVED_MARKER = PRIVATE_MARKER + b"_ONE_PAID_TURN_DEVICE_OBSERVED\0"
CONTINUOUS_MARKER = PRIVATE_MARKER + b"_CONTINUOUS"
REBOOT_TRIAL_MARKER = PRIVATE_MARKER + b"_REBOOT_TRIAL\0"


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


def inspect_image(
    app: bytes, elf_sha256: str, partition_csv: str, *, local_one_turn: bool = False
) -> dict:
    envelope = inspect_model_image(app, elf_sha256, b"k151_conversation_review")
    if local_one_turn:
        measured = ONE_TURN_MARKER in app
        device_observed = DEVICE_OBSERVED_MARKER in app
        if (
            PUBLIC_MARKER in app
            or CONTINUOUS_MARKER in app
            or REBOOT_TRIAL_MARKER in app
            or measured == device_observed
        ):
            raise ValueError("mixed or incompatible conversation image")
    elif PRIVATE_MARKER in app:
        raise ValueError("private release marker in public conversation image")
    elif PUBLIC_MARKER not in app:
        # ESP_LOGW wraps this marker in its format string, including a newline.
        raise ValueError("missing public conversation marker")
    markers = (
        b"Say Hi StackChan\0",
        b"Standby verified. Trial ended.\0",
    )
    for marker in markers:
        if marker not in app:
            raise ValueError(f"missing expected conversation marker {marker!r}")
    verify_realtime_transport(app)
    result = {
        **envelope,
        **validate_slot(
            partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"], require_nvs=local_one_turn
        ),
        "kind": "LOCAL_ONE_PAID_TURN_REVIEW"
        if local_one_turn
        else "CONVERSATION_REVIEW_NO_RELEASE",
        "private_board_policy_embedded": local_one_turn,
        "cloud_enabled_at_boot": False,
        "paid_api_called": False,
        "physical_output_or_stop_proven": False,
    }
    if local_one_turn:
        result["one_turn_output_basis"] = (
            "device_diagnostics" if device_observed else "electrical_measurement"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("elf", "bin", "partition-csv", "sdkconfig", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--idf-head", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--local-one-turn", action="store_true")
    for name in ("factory-a", "factory-b", "factory-ota1", "pretrial-nvs"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--factory-sha256")
    args = parser.parse_args(argv)
    restore = (
        args.factory_a,
        args.factory_b,
        args.factory_sha256,
        args.factory_ota1,
        args.pretrial_nvs,
    )
    if args.local_one_turn and ("CI" in os.environ or not all(restore)):
        parser.error("local one-turn review requires local execution and all restore inputs")
    if not args.local_one_turn and any(restore):
        parser.error("restore inputs are only supported for local one-turn review")

    try:
        validate_source_head(args.source_head)
        verify_sdkconfig(args.sdkconfig.read_text(encoding="utf-8"))
        base = validate(args.elf, args.bin, args.idf_head)
        result = inspect_image(
            args.bin.read_bytes(),
            base["elf"]["sha256"],
            args.partition_csv.read_text(encoding="utf-8"),
            local_one_turn=args.local_one_turn,
        )
        result.update(
            idf_commit=base["idf_commit"],
            elf=base["elf"],
            source_head=bind_source_head(result["app_version"], args.source_head),
            psram_console_and_task_config_verified=True,
        )
        if args.local_one_turn:
            result["runtime_budget_write_scope"] = "sc_gpt/budget"
            result["recovery"] = verify_trial_restore(*restore)
        with args.out.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError, Rejected):
        if not args.local_one_turn:
            raise
        print("LOCAL_ONE_PAID_TURN_REVIEW_REJECTED")
        return 2
    if args.local_one_turn:
        print("LOCAL_ONE_PAID_TURN_REVIEW_WRITTEN_NO_AUTHORIZATION")
    else:
        print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

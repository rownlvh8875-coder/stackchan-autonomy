"""Bind a K151 conversation image and its local trial restore review."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from check_board_probe import validate_slot
from check_idf_build import validate, verify_realtime_transport
from check_resource_bench import inspect_model_image
from check_trial_budget_snapshot import inspect_pinned_snapshot
from esp_app_image import SLOT_OFFSET, bind_source_head, validate_source_head
from offline_factory_recovery import Rejected, verify_trial_restore
from paid_trial_sequence import REBOOT_TRIAL_BUDGET_KEYS, REBOOT_TRIAL_PAID_TURNS

PUBLIC_MARKER = b"K151_CONVERSATION_REVIEW_NO_RELEASE"
PRIVATE_MARKER = b"K151_CONVERSATION_LOCAL_RELEASE"
ONE_TURN_MARKER = PRIVATE_MARKER + b"_ONE_PAID_TURN\0"
DEVICE_OBSERVED_MARKER = PRIVATE_MARKER + b"_ONE_PAID_TURN_DEVICE_OBSERVED\0"
CONTINUOUS_MARKER = PRIVATE_MARKER + b"_CONTINUOUS"
REBOOT_TRIAL_MARKER = PRIVATE_MARKER + b"_REBOOT_TRIAL\0"


def verify_reboot_trial_marker(app: bytes) -> None:
    if REBOOT_TRIAL_MARKER not in app or any(
        marker in app
        for marker in (PUBLIC_MARKER, ONE_TURN_MARKER, DEVICE_OBSERVED_MARKER, CONTINUOUS_MARKER)
    ):
        raise ValueError("mixed or incompatible reboot trial image")


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
    app: bytes,
    elf_sha256: str,
    partition_csv: str,
    *,
    local_one_turn: bool = False,
    local_reboot_trial: bool = False,
) -> dict:
    if local_one_turn and local_reboot_trial:
        raise ValueError("choose one local review mode")
    envelope = inspect_model_image(app, elf_sha256, b"k151_conversation_review")
    if local_reboot_trial:
        verify_reboot_trial_marker(app)
    elif local_one_turn:
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
    markers = (b"Say Hi StackChan\0",)
    if local_reboot_trial:
        markers += (b"Reboot ready. Power off and on.\0", b"Previous budget verified\0")
    else:
        markers += (b"Standby verified. Trial ended.\0",)
    for marker in markers:
        if marker not in app:
            raise ValueError(f"missing expected conversation marker {marker!r}")
    verify_realtime_transport(app)
    local = local_one_turn or local_reboot_trial
    kind = "CONVERSATION_REVIEW_NO_RELEASE"
    if local_reboot_trial:
        kind = "LOCAL_REBOOT_PAID_TRIAL_REVIEW"
    elif local_one_turn:
        kind = "LOCAL_ONE_PAID_TURN_REVIEW"
    result = {
        **envelope,
        **validate_slot(
            partition_csv, SLOT_OFFSET, envelope["erase_span_bytes"], require_nvs=local
        ),
        "kind": kind,
        "private_board_policy_embedded": local,
        "cloud_enabled_at_boot": False,
        "paid_api_called": False,
        "physical_output_or_stop_proven": False,
    }
    if local_reboot_trial:
        result.update(
            reboot_trial_paid_turns=dict(REBOOT_TRIAL_PAID_TURNS),
            runtime_budget_write_scope=list(REBOOT_TRIAL_BUDGET_KEYS),
            runtime_owner_setup_write_scope="sc_owner/owner_cfg_v2",
        )
    elif local_one_turn:
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--local-one-turn", action="store_true")
    mode.add_argument("--local-reboot-trial", action="store_true")
    parser.add_argument(
        "--idf-dir", type=Path, help="Pinned IDF checkout for the reboot budget review"
    )
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
    local = args.local_one_turn or args.local_reboot_trial
    if local and ("CI" in os.environ or not all(restore)):
        parser.error("a private trial review requires local execution and all restore inputs")
    if not local and any(restore):
        parser.error("restore inputs are only supported for a private trial review")
    if args.local_reboot_trial != (args.idf_dir is not None):
        parser.error("--idf-dir is required only for --local-reboot-trial")
    local_kind = (
        "LOCAL_REBOOT_PAID_TRIAL_REVIEW"
        if args.local_reboot_trial
        else "LOCAL_ONE_PAID_TURN_REVIEW"
    )

    try:
        validate_source_head(args.source_head)
        verify_sdkconfig(args.sdkconfig.read_text(encoding="utf-8"))
        base = validate(args.elf, args.bin, args.idf_head)
        result = inspect_image(
            args.bin.read_bytes(),
            base["elf"]["sha256"],
            args.partition_csv.read_text(encoding="utf-8"),
            local_one_turn=args.local_one_turn,
            local_reboot_trial=args.local_reboot_trial,
        )
        result.update(
            idf_commit=base["idf_commit"],
            elf=base["elf"],
            source_head=bind_source_head(result["app_version"], args.source_head),
            psram_console_and_task_config_verified=True,
        )
        if local:
            result["recovery"] = verify_trial_restore(*restore)
        if args.local_one_turn:
            result["runtime_budget_write_scope"] = "sc_gpt/budget"
        if args.local_reboot_trial:
            baseline = inspect_pinned_snapshot(
                args.pretrial_nvs, args.idf_dir, require_fresh_reboot_trial=True
            )
            if (
                baseline["pretrial_nvs_sha256"]
                != result["recovery"]["restore_in_order"][1]["sha256"]
            ):
                raise ValueError("pretrial NVS changed during review")
            result["fresh_reboot_state_verified"] = True
            result["budget_baseline"] = {
                field: baseline[field]
                for field in (
                    "pretrial_nvs_sha256",
                    "trial_budget_must_be_missing",
                    "trial_budget_sha256",
                )
            }
        with args.out.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError, Rejected, KeyError, TypeError, subprocess.SubprocessError):
        if not local:
            raise
        print(f"{local_kind}_REJECTED")
        return 2
    if local:
        print(f"{local_kind}_WRITTEN_NO_AUTHORIZATION")
    else:
        print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

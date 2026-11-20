"""Read-only source-level K151 release blocker report.

No device, serial port, Wi-Fi, secrets, factory backup or API access.
This report can NEVER grant device installation approval.
"""

import argparse
import json
from pathlib import Path

REQUIRED_PHYSICAL_PROOFS = (
    "two independently restorable factory backups and off-device copy",
    "factory active OTA slot and compatible partition boot path",
    "exact board revision and exclusive I2C ownership",
    "measured AXP2101 rails and verified AW9523 reset",
    "measured AW88298 electrical hard mute and power sequencing",
    "independently measured STOP-to-mute latency",
    "hardware-observed TX DMA empty plus codec output idle",
    "actual mic/codec 24 kHz timing and dual-channel mapping",
    "live Korean '조수야' detection and false-wake results",
    "verified allocator PSRAM placement and measured peak RAM",
    "owner-authorized installation and restoration rehearsal",
)


def source_invariants(root: Path) -> dict[str, bool]:
    def read(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    policy = read("core/k151_output_evidence.hpp")
    codec = read("esp_app/main/k151_codec_port.cpp")
    boot = read("esp_app/main/app_main.cpp")
    memory = read("core/audio_memory_admission.hpp")
    return {
        "hold_output_hard_disabled": "kK151PhysicalOutputEnabledInHoldImage = false" in policy,
        "physical_dma_driver_hard_disabled": "kK151SafeDmaDrainDriverAvailable = false" in policy,
        "codec_blocks_amp_without_both_gates": (
            "if (!kK151PhysicalOutputEnabledInHoldImage ||" in codec
            and "!kK151SafeDmaDrainDriverAvailable) return false;" in codec
        ),
        "boot_perpetually_holds": "for (;;) vTaskDelay(pdMS_TO_TICKS(1000));" in boot,
        "memory_cannot_authorize_install": "kAudioMemoryReadinessCanAuthorizeInstall = false"
        in memory,
        "no_install_approval_manifest": (
            (root / "esp_app/NOT_APPROVED_FOR_DEVICE_INSTALLATION.txt").is_file()
        ),
    }


def inspect_readiness(root: Path) -> dict:
    invariants = source_invariants(root)
    return {
        "status": "BLOCKED_SOURCE_REGRESSION"
        if not all(invariants.values())
        else "NOT_APPROVED_FOR_DEVICE_INSTALLATION",
        "source_invariants": invariants,
        "physical_proofs_not_verified_here": REQUIRED_PHYSICAL_PROOFS,
        "source_checks_all_pass": all(invariants.values()),
        "hardware_accessed": False,
        "factory_backups_read": False,
        "api_or_network_accessed": False,
        "install_authorized": False,
        "firmware_or_ota_modified": False,
        "explanation": "Source checks do not prove hardware readiness or permit flashing.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="standalone source root for read-only inspection",
    )
    args = parser.parse_args(argv)
    try:
        report = inspect_readiness(args.root.resolve())
    except (OSError, UnicodeError) as exc:
        print(
            json.dumps(
                {
                    "status": "SOURCE_UNAVAILABLE",
                    "error_kind": type(exc).__name__,
                    "install_authorized": False,
                }
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["source_checks_all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

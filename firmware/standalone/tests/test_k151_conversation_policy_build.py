"""Exercise the K151 operating admission rules without a connected device."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_k151_conversation_boot_policy(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "policy"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(root / "core"),
            "-I",
            str(root / "esp_app/main"),
            str(root / "tests/k151_conversation_policy_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)


@pytest.mark.parametrize(
    ("mode", "first_budget", "device_observed", "owner_slot", "marker"),
    [
        ("hold", False, False, None, None),
        ("one_paid_turn", False, False, None, b"ONE_PAID_TURN"),
        ("one_paid_turn", True, False, None, b"ONE_PAID_TURN"),
        ("one_paid_turn", False, True, None, b"ONE_PAID_TURN_DEVICE_OBSERVED"),
        ("one_paid_turn", True, True, None, b"ONE_PAID_TURN_DEVICE_OBSERVED"),
        ("one_paid_turn", False, False, 1, None),
        ("continuous", False, False, None, None),
        ("continuous", False, False, 0, b"CONTINUOUS"),
        ("continuous", False, True, 0, None),
        ("continuous", False, False, "local", b"CONTINUOUS_LOCAL_UNLOCK"),
        ("continuous", False, True, "local", None),
        ("reboot_trial", False, False, "local", b"REBOOT_TRIAL"),
        ("reboot_trial", True, False, "local", b"REBOOT_TRIAL"),
        ("reboot_trial", True, True, "local", None),
        ("reboot_trial", True, False, 1, None),
        ("one_paid_turn", True, False, "local", None),
    ],
)
def test_local_policy_marker_requires_complete_compiled_scope(
    tmp_path, mode, first_budget, device_observed, owner_slot, marker
):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    root = Path(__file__).resolve().parents[1]
    app = root / "esp_app/main"
    psa = tmp_path / "psa"
    psa.mkdir()
    (psa / "crypto.h").write_text(
        "#pragma once\n#include <cstddef>\n#include <cstdint>\n"
        "inline constexpr int PSA_SUCCESS = 0, PSA_ALG_SHA_256 = 1;\n"
        "int psa_crypto_init();\n"
        "int psa_hash_compute(int, const uint8_t*, size_t, uint8_t*, size_t, size_t*);\n"
    )
    # These are compile-only fixtures with a synthetic identity. No firmware is linked.
    trial_budget = ""
    if first_budget:
        trial_budget = ",\n.trial_budget_must_be_missing = true"
    elif mode in ("one_paid_turn", "reboot_trial"):
        trial_budget = ",\n.trial_budget_sha256 = K151BudgetDigest{2}"
    output = (
        "{true, true, false, false, false, false, true}"
        if device_observed
        else ("{true, true, true, true, true, true, true}")
    )
    observed = (
        ",\n.one_turn_device_evidence = K151OneTurnDeviceEvidence{{1}, {2}, {3}}"
        if device_observed
        else ""
    )
    slot = (
        ",\n.reversible_owner_unlock = true"
        if owner_slot == "local"
        else f",\n.owner_hmac_slot = {owner_slot}"
        if owner_slot is not None
        else ""
    )
    reboot_id = ",\n.reboot_trial_id = K151BudgetDigest{3}" if mode == "reboot_trial" else ""
    (tmp_path / "k151_private_policy.inc").write_text(
        "{\n.expected_factory_identity = {1},\n"
        f".output = {output},\n"
        ".physical_lcd_verified = true,\n.exclusive_i2s0_verified = true,\n"
        f".paid_scope_approved = true,\n.budget_scope_approved = true,\n"
        f".allow_first_budget = {str(first_budget).lower()},\n"
        f".mode = K151ConversationBuildMode::{mode}{trial_budget}{observed}{slot}{reboot_id}\n}}\n"
    )
    object_file = tmp_path / "policy.o"
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-DSTACKCHAN_K151_PRIVATE_POLICY=1",
            "-I",
            str(tmp_path),
            "-I",
            str(root / "core"),
            "-c",
            str(app / "k151_conversation_policy.cpp"),
            "-o",
            str(object_file),
        ],
        capture_output=True,
        timeout=60,
    )
    if marker is None:
        assert (
            result.returncode != 0
            and b"Incomplete private K151 operating evidence" in result.stderr
        )
    else:
        assert result.returncode == 0, result.stderr
        data = object_file.read_bytes()
        for suffix in (
            b"ONE_PAID_TURN",
            b"ONE_PAID_TURN_DEVICE_OBSERVED",
            b"CONTINUOUS",
            b"CONTINUOUS_LOCAL_UNLOCK",
            b"REBOOT_TRIAL",
        ):
            assert (b"K151_CONVERSATION_LOCAL_RELEASE_" + suffix + b"\0" in data) == (
                suffix == marker
            )

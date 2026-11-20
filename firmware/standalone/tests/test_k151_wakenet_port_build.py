"""Public SDK ABI doubles; no actual neural model, board, microphone or network."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required; Linux CI provides it")
    binary = tmp_path_factory.mktemp("sdk-wake") / "sdk-wake"
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(BASE / "tests/idf_partition_doubles"),
            "-I",
            str(BASE / "tests/sdk_esp_sr_2_4_7"),
            "-I",
            str(BASE / "core"),
            "-I",
            str(BASE / "esp_app/main"),
            str(BASE / "tests/k151_wakenet_port_test.cpp"),
            str(BASE / "esp_app/main/k151_wakenet_port.cpp"),
            str(BASE / "esp_app/main/k151_model_assets.cpp"),
            str(BASE / "esp_app/main/k151_embedded_assets.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    return binary, result


@pytest.mark.parametrize(
    "case",
    [
        "embedded_valid",
        "embedded_bad_size",
        "embedded_mutable",
        "embedded_psram",
        "embedded_bad_hash",
        "embedded_hash_error",
        "embedded_no_owner",
        "embedded_stopped",
        "embedded_revoke_hash",
        "embedded_revoke_load",
        "embedded_stop_create",
        "embedded_overlap",
        "local_valid",
        "local_no_owner",
        "local_stopped",
        "local_missing",
        "local_bad_size",
        "local_bad_address",
        "local_bad_type",
        "local_bad_label",
        "local_writable",
        "local_encrypted",
        "local_external",
        "local_bad_hash",
        "local_hash_error",
        "local_revoke_find",
        "local_revoke_hash",
        "local_stop_hash",
        "local_revoke_create",
        "local_revoke_init",
        "local_stop_filter",
        "overlap",
        "preexisting_sdk",
        "gate",
        "valid",
        "closed",
        "unknown",
        "wrong_buffer",
        "missing_list",
        "multiple",
        "missing_name",
        "wrong_name",
        "missing_iface",
        "create_failure",
        "rate",
        "channel",
        "words",
        "chunk_negative",
        "chunk_small",
        "chunk_large",
        "no_create",
        "no_rate",
        "no_channel",
        "no_chunk",
        "no_words",
        "no_detect",
        "no_clean",
        "no_destroy",
    ],
)
def test_sdk_wake_case(compiled, case):
    binary, result = compiled
    assert result.returncode == 0, result.stderr
    completed = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr

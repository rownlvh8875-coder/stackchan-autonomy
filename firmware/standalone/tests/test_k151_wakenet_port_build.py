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
            str(BASE / "tests/sdk_esp_sr_2_4_7"),
            "-I",
            str(BASE / "core"),
            "-I",
            str(BASE / "esp_app/main"),
            str(BASE / "tests/k151_wakenet_port_test.cpp"),
            str(BASE / "esp_app/main/k151_wakenet_port.cpp"),
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

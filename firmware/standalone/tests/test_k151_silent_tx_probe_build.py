"""Exercise the real silent TX diagnostic through SDK doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def silent_tx_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("silent-tx") / "probe"
    command = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    for directory in ("tests/codec_io_doubles", "esp_app/main"):
        command += ["-I", str(BASE / directory)]
    command += [
        str(BASE / "esp_app/main/k151_silent_tx_probe.cpp"),
        str(BASE / "tests/k151_silent_tx_probe_test.cpp"),
        "-o",
        str(binary),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "ok",
        "denied",
        "stop_before",
        "timeout",
        "late",
        "duplicate",
        "bad_event",
        "clock_rollback",
        "stop",
        "owner_revoked",
        "register_failure",
        "short_preload",
        "enable_failure",
        "disable_failure",
        "delete_failure",
    ],
)
def test_gpio_isolated_tx_observation(silent_tx_binary, case):
    result = subprocess.run(
        [str(silent_tx_binary), case], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr

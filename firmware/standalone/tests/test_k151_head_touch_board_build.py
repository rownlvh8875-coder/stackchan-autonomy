"""Exercise the actual Si12T adapter with an offline register model."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
APP = BASE / "esp_app/main"


@pytest.fixture(scope="module")
def sensor_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("k151-head-touch") / "head-touch"
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
            str(BASE / "tests/codec_io_doubles"),
            "-I",
            str(BASE / "core"),
            "-I",
            str(APP),
            str(BASE / "tests/k151_head_touch_board_test.cpp"),
            str(APP / "k151_head_touch_owner.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "cold",
        "configured",
        "readonly",
        "wrong_config",
        "unverified",
        "bus_not_exclusive",
        "wrong_bus",
        "stopped",
        "read_error",
        "readback_mismatch",
        "ambiguous_write",
        "stop_during_write",
        "stop_during_settle",
        "stop_after_consent",
        "clock_error",
        "clock_rollback",
        "reset_during_settle",
        "poll_error",
        "cleanup_retry",
    ],
)
def test_sensor_board_lifecycle(sensor_binary, case):
    ran = subprocess.run([str(sensor_binary), case], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stderr

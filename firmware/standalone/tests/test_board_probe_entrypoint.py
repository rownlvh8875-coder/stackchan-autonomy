"""Execute the actual diagnostic entry point: wrong location never opens USB/I2C."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def entrypoint(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("board-entry") / "entry"
    built = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(BASE / "tests/board_probe_doubles"),
            "-I",
            str(BASE / "core"),
            "-I",
            str(BASE / "esp_app/main"),
            "-I",
            str(BASE / "resource_bench/main"),
            str(BASE / "board_probe/main/app_main.cpp"),
            str(BASE / "tests/board_probe_entrypoint_test.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize("kind", ["missing", "slot", "chip", "revision"])
def test_denial_preserves_actual_location(entrypoint, kind):
    result = subprocess.run([str(entrypoint), kind], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    identity = records[0]
    assert identity["partition_present"] is (kind != "missing")
    assert identity["chip_model"] == (1 if kind == "chip" else 9)
    assert identity["chip_revision"] == (3 if kind == "revision" else 2)
    assert identity["running_offset"] == (
        None if kind == "missing" else 0x20000 if kind == "slot" else 0x510000
    )
    assert identity["running_size"] == (None if kind == "missing" else 0x4F0000)
    assert records[-1] == {"result": "RUNNING_LOCATION_OR_CHIP_DENIED"}

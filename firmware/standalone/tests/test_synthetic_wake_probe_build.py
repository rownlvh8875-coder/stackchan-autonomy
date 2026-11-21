"""Execute the real synthetic wake bench phase with host doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("synthetic-wake-probe") / "probe"
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(BASE / "core"),
            "-I",
            str(BASE / "resource_bench/main"),
            str(BASE / "tests/synthetic_wake_probe_test.cpp"),
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
    "mode",
    [
        "complete",
        "first_poll_detect",
        "denied",
        "trace_error",
        "reset_failure",
        "stop_before_detect",
        "detect_interrupted",
    ],
)
def test_checkpoint_boundaries(probe, mode):
    result = subprocess.run([str(probe), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

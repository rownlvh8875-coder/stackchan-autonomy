"""Execute actual probe against I2C C ABI doubles, no hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def probe_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("probe") / "probe"
    built = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(BASE / "tests/idf_i2c_doubles"),
            "-I",
            str(BASE / "core"),
            "-I",
            str(BASE / "esp_app/main"),
            str(BASE / "tests/k151_readonly_probe_test.cpp"),
            str(BASE / "esp_app/main/k151_readonly_probe.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize("mode", ["ok", "absent", "denied", "stopped"])
def test_actual_probe(probe_binary, mode):
    run = subprocess.run([str(probe_binary), mode], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("mode", ["stop", "revoke", "fail"])
@pytest.mark.parametrize("at", range(26))
def test_every_sdk_boundary(probe_binary, mode, at):
    run = subprocess.run(
        [str(probe_binary), mode, str(at)], capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize(
    "mode",
    [
        "power_ok",
        "power_disabled",
        "power_wrong_ids",
        "power_invalid",
        "power_default",
        "power_absent",
    ],
)
def test_power_readback_reports_only_identified_enabled_sources(probe_binary, mode):
    run = subprocess.run([str(probe_binary), mode], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("mode", ["stop", "revoke", "fail"])
@pytest.mark.parametrize("at", range(15))
def test_power_readback_discards_partial_result_at_every_sdk_boundary(probe_binary, mode, at):
    run = subprocess.run(
        [str(probe_binary), mode, str(at), "power"], capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0, run.stderr

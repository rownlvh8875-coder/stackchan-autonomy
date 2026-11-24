"""Execute the actual diagnostic entry point against host SDK doubles."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


def build_entrypoint(tmp_path_factory, *, power=False):
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
            "-pthread",
            *(["-DSTACKCHAN_K151_POWER_READBACK=1"] if power else []),
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


@pytest.fixture(scope="module")
def entrypoint(tmp_path_factory):
    return build_entrypoint(tmp_path_factory)


@pytest.fixture(scope="module")
def power_entrypoint(tmp_path_factory):
    return build_entrypoint(tmp_path_factory, power=True)


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


def test_report_retains_old_fields_and_includes_audio_registers(entrypoint):
    result = subprocess.run([str(entrypoint), "report"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    report = next(record for record in records if record.get("probe") == "READBACK_COMPLETED")
    assert report["ack"] == [1, 1, 1, 0, 1]
    assert report["pmic_id_valid"] == 1 and report["pmic_id"] == 0x4A
    assert report["pmic_ldo_valid"] == 1
    assert report["pmic_regs"] == [0x90, 0x94, 0x95, 0x97, 0x99]
    assert report["pmic_values"] == [0xBF, 0x1C, 0x1C, 0x1C, 0x1A]
    assert report["pmic_aldo12_valid"] == 1
    assert report["pmic_aldo12_values"] == [0x0D, 0x1C]
    assert report["aw_id_valid"] == 1 and report["aw_id"] == 0x23
    assert report["aw_outputs_valid"] == 1 and report["aw_outputs"] == [0x07, 0x83]
    assert report["aw_directions_valid"] == 1 and report["aw_directions"] == [0x18, 0x0C]
    assert report["aw_p0_mode_valid"] == 1
    assert report["aw_p0_mode"] == 0xFD
    assert report["touch_valid"] == 1
    assert report["touch_version"] == [0x64, 0x01, 0x01, 0x12, 0x00, 0x11]
    assert report["operating_admission"] is False
    assert records[-1] == {"probe": "HOLD_UNTIL_RESET", "operating_admission": False}


def test_power_readback_reports_adc_availability_and_then_holds(power_entrypoint):
    run = subprocess.run(
        [str(power_entrypoint), "report"], capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0, run.stderr
    records = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    assert records[1] == {"probe": "WAIT_POWER_LOCAL_START", "nonce": "00000001", "wait_ms": 60000}
    assert records[2] == {
        "probe": "K151_POWER_READBACK_V1",
        "pmic_vsys": "sampled",
        "pmic_vsys_mv": 3700,
        "amp_vdd": "reset_value",
        "amp_vdd_mv": 0,
        "amp_uvls": True,
        "operating_admission": False,
    }
    assert records[3:] == [{"probe": "HOLD_UNTIL_RESET", "operating_admission": False}]

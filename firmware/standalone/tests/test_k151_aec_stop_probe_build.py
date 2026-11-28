"""Compile the sample-timing diagnostic against synthetic DMA blocks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def compile_probe(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("C++20 compiler required")
    root = Path(__file__).resolve().parents[1]

    def run(*sources):
        binary = tmp_path / "k151_aec_stop_probe"
        build = subprocess.run(
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
                *(str(root / source) for source in sources),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert build.returncode == 0, build.stderr
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout

    return run


def test_aec_stop_probe_analyzes_only_the_reference_lane(compile_probe):
    assert not compile_probe("tests/k151_aec_stop_probe_test.cpp")


def test_app_entrypoint_exports_only_synthetic_summary(compile_probe, tmp_path):
    entrypoint = tmp_path / "host_main.cpp"
    entrypoint.write_text('extern "C" void app_main();\nint main() { app_main(); }\n')
    output = compile_probe(entrypoint, "aec_stop_probe/main/app_main.cpp").splitlines()
    assert output[0] == "K151_AEC_STOP_SYNTHETIC_ONLY_HOLD"
    assert len(output) == 2
    assert json.loads(output[1]) == {
        "aec_selftest": "passed",
        "sample_rate_hz": 24_000,
        "stop_frame": 960,
        "first_possible_frame": 984,
        "quiet_by_frame": 1_032,
        "hardware_observed": False,
    }

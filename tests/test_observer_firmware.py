"""Compile the actual portable firmware core; this is explicitly not an ESP32 build."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_observer import literal

from stackchan_autonomy.observer_protocol import FrameReader

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_isolated_camera_queue_validates_raw_memory(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        if os.name != "nt":
            pytest.fail("Linux C++ host compiler is required")
        pytest.skip("C++ host compiler unavailable")
    executable = tmp_path / ("camera.exe" if os.name == "nt" else "camera")
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-Ifirmware/observer/core",
            "firmware/observer/tests/camera_test.cpp",
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    subprocess.run([str(executable)], check=True)


@pytest.fixture(scope="module")
def host_core(tmp_path_factory):
    compiler = shutil.which("g++")
    if compiler is None:
        if os.name != "nt":
            pytest.fail("Linux C++ host compiler is required")
        pytest.skip("C++ host compiler unavailable; ESP32 build is a separate check")
    target = tmp_path_factory.mktemp("observer-host") / (
        "core-test.exe" if os.name == "nt" else "core-test"
    )
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-Ifirmware/observer/core",
            "firmware/observer/tests/core_test.cpp",
            "firmware/observer/core/observer_core.cpp",
            "-o",
            str(target),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return target


def test_portable_dispatcher_whitelist_bounds_and_camera_release(host_core):
    result = subprocess.run([str(host_core)], capture_output=True, check=True)
    assert result.stdout == b"HOST_CORE_PASS\n"


def test_python_literal_request_interoperates_with_firmware_core(host_core):
    nonce = bytes(range(16))
    wire = b"boot noise" + literal(1, nonce)
    result = subprocess.run([str(host_core), "wire"], input=wire, capture_output=True, check=True)
    reader = FrameReader()
    kind, received, payload = reader.feed(result.stdout)
    assert kind == 0x81 and received == nonce
    assert b'"read_only":true' in payload and b'"unofficial-observer-prototype"' in payload

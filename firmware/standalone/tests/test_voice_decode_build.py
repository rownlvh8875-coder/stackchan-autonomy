"""Compile and execute response decoder fixtures against system cJSON on Linux."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_standalone_voice_decoder_host(tmp_path):
    compiler = shutil.which("g++")
    header = Path("/usr/include/cjson/cJSON.h")
    if compiler is None or not header.is_file():
        pytest.skip("system libcjson-dev headers unavailable")
    root = Path(__file__).resolve().parents[1]
    exe = tmp_path / "voice_decode"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(header.parent),
            "-I",
            str(root / "core"),
            "-I",
            str(root / "esp_app" / "main"),
            str(root / "esp_app" / "main" / "k151_voice_decode.cpp"),
            str(root / "tests" / "voice_decode_test.cpp"),
            "-lcjson",
            "-o",
            str(exe),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(exe)], check=True, timeout=30)

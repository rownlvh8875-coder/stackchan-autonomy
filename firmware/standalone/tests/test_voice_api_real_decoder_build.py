"""Test full typed voice bridge against the real cJSON/PCM decoder, offline."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_voice_api_real_decoder_host(tmp_path):
    compiler = shutil.which("g++")
    header = Path("/usr/include/cjson/cJSON.h")
    if compiler is None or not header.exists():
        pytest.skip("Linux libcjson-dev header or g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "voice_api_real_decoder_test"
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
            "-I",
            str(root / "resource_bench" / "main"),
            str(root / "esp_app" / "main" / "k151_voice_decode.cpp"),
            str(root / "tests" / "voice_api_real_decoder_test.cpp"),
            "-lcjson",
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

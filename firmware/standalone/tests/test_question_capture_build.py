"""Exercise bounded offline PCM segmenter with a host C++20 compiler."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_question_capture_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI provides compiler")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "question_capture_test"
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
            str(root / "core"),
            "-I",
            str(root / "esp_app" / "main"),
            "-I",
            str(root / "tests" / "codec_io_doubles"),
            "-I",
            str(root / "tests" / "idf_partition_doubles"),
            str(root / "tests" / "question_capture_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

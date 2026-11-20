"""Compile and exercise the strict audio peak-RAM diagnostic gate offline."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_audio_memory_admission_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI supplies compiler")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "audio_memory_admission_test"
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
            str(root / "tests" / "audio_memory_admission_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

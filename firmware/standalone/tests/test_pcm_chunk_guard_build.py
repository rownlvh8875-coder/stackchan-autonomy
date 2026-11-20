"""Compile and execute bounded PCM stop/deadline guards without hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_pcm_chunk_guard_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI provides compiler")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "pcm_chunk_guard_test"
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
            str(root / "tests" / "pcm_chunk_guard_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

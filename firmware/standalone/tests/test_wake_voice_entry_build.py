"""Compile and run local wake-to-fake-GPT integration without hardware/API."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_wake_voice_entry_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI supplies compiler")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "wake_voice_entry_test"
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
            str(root / "tests" / "wake_voice_entry_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

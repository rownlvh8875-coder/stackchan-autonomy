"""Host-only C++20 integration: fake K151 mic -> session -> fake GPT reply."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_voice_turn_coordinator_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI supplies C++20 compiler")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "voice_turn_coordinator_test"
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
            str(root / "tests" / "voice_turn_coordinator_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

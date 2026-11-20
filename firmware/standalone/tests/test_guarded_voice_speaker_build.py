"""Host-only C++20 test for mute-first / one-way speaker STOP lifecycle."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_guarded_voice_speaker_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI supplies C++20 compiler")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "guarded_voice_speaker_test"
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
            str(root / "tests" / "guarded_voice_speaker_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

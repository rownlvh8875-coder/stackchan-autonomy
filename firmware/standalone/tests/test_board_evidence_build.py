"""Host-only evidence parser: no USB, I2C, physical device or cloud."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_board_evidence_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    exe = tmp_path / "board_evidence_test"
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
            str(root / "tests" / "board_evidence_test.cpp"),
            "-o",
            str(exe),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(exe)], check=True, timeout=30)

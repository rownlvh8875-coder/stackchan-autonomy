"""Compile and run the standalone credential-free screen model on host."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_setup_screen_model_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "setup_screen_model_test"
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
            str(root / "tests" / "setup_screen_model_test.cpp"),
            "-o",
            str(output),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(output)], check=True, timeout=30)

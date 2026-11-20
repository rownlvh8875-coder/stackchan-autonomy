"""Build and run the trusted local-owner provisioning state machine offline."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_owner_setup_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ not available")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "owner_setup_test"
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
            str(root / "tests" / "owner_setup_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

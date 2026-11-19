"""Run isolated network/time policy checks without radio, sockets or secrets."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_network_time_guard_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "network_time_guard_test"
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
            str(root / "tests" / "network_time_guard_test.cpp"),
            "-o",
            str(output),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(output)], check=True, timeout=30)

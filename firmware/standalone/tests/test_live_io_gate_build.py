"""Compile and execute the network/STOP I/O revocation gate without sockets."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_live_io_gate_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "live_io_gate_test"
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
            str(root / "tests" / "live_io_gate_test.cpp"),
            "-o",
            str(output),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(output)], check=True, timeout=30)

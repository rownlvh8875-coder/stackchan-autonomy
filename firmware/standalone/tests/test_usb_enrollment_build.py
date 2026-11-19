"""Compile and execute the K151 USB enrollment receiver entirely on a host."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_usb_enrollment_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ not available")
    root = Path(__file__).resolve().parents[1]
    source = root / "tests" / "usb_enrollment_test.cpp"
    output = tmp_path / "usb_enrollment_test"
    args = [
        compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-I", str(root / "core"), str(source), "-o", str(output),
    ]
    subprocess.run(args, check=True, timeout=90)
    subprocess.run([str(output)], check=True, timeout=30)

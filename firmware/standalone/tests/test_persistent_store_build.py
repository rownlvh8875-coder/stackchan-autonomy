"""Compile and run the isolated persistence contract with no device access."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_persistent_store_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    args = [
        compiler,
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-I",
        str(root / "core"),
        str(root / "tests" / "persistent_store_test.cpp"),
        "-o",
        str(tmp_path / "persistent_store_test"),
    ]
    subprocess.run(args, check=True, timeout=90)
    subprocess.run([str(tmp_path / "persistent_store_test")], check=True, timeout=30)

"""Build the shared wake-phrase DSP on the host using synthetic audio."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_wake_feature_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ not available")
    root = Path(__file__).resolve().parents[1]
    source = root / "tests" / "wake_features_test.cpp"
    exe = tmp_path / "wake_features_test"
    if sys.platform == "win32":
        exe = exe.with_suffix(".exe")
    flags = ["-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    args = [compiler, *flags, "-I", str(root / "core"), str(source), "-o", str(exe)]
    subprocess.run(args, check=True, timeout=90)
    subprocess.run([str(exe)], check=True, timeout=30)

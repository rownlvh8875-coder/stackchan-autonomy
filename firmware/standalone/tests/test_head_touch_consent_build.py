"""Build and run the K151 two-stage physical-presence gesture policy offline."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_head_touch_consent_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "head_touch_consent_test"
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
            str(root / "tests" / "head_touch_consent_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(binary)], check=True, timeout=30)

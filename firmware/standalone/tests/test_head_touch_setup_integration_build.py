"""Exercise physical-presence gate alongside existing owner-only RAM setup."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_head_touch_owner_setup_integration(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "head_touch_owner_integration"
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
            str(root / "tests" / "head_touch_setup_integration_test.cpp"),
            "-o",
            str(target),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(target)], check=True, timeout=30)

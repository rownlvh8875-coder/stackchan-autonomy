"""Exercise the K151 operating admission rules without a connected device."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_k151_conversation_boot_policy(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "policy"
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
            "-I",
            str(root / "esp_app/main"),
            str(root / "tests/k151_conversation_policy_test.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)

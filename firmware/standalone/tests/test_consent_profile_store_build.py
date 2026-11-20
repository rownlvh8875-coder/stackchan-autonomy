"""Compile K151 independent consent-to-NVS bridge without touching hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_consent_profile_store_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ is unavailable")
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "consent_profile_store_test"
    command = [
        compiler,
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-I",
        str(root / "core"),
        str(root / "tests" / "consent_profile_store_test.cpp"),
        "-o",
        str(target),
    ]
    subprocess.run(command, check=True, timeout=90)
    subprocess.run([str(target)], check=True, timeout=30)

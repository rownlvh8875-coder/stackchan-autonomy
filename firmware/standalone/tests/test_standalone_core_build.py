"""Compile and exercise the portable standalone safety core offline."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_portable_standalone_core(tmp_path: Path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("g++ unavailable; no host C++ compiler on this CI runner")
    exe = tmp_path / (
        "standalone_core_test.exe" if os.name == "nt" else "standalone_core_test"
    )
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
            str(ROOT / "core"),
            str(ROOT / "tests" / "standalone_core_test.cpp"),
            "-o",
            str(exe),
        ],
        check=True,
        cwd=ROOT,
        timeout=90,
    )
    output = subprocess.run(
        [str(exe)], check=True, capture_output=True, text=True, timeout=30
    )
    assert "standalone core: PASS" in output.stdout

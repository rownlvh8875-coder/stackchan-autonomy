"""Compile and run portable OpenAI HTTP body and bounded response tests offline."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_openai_http_wire(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    exe = tmp_path / "http_wire"
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
            str(root / "tests" / "http_wire_test.cpp"),
            "-o",
            str(exe),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(exe)], check=True, timeout=30)

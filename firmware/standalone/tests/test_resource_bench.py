"""Finite local bench consent, host-only; no USB/device access."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


def test_local_gate(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path / "gate"
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(BASE / "resource_bench/main"),
            str(BASE / "tests/resource_bench_gate_test.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    completed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr


def test_post_model_heap_window(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path / "heap-window"
    command = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    for directory in ("resource_bench/main", "core", "tests/codec_io_doubles"):
        command += ["-I", str(BASE / directory)]
    source = BASE / "tests/resource_bench_heap_window_test.cpp"
    result = subprocess.run(
        command + [str(source), "-o", str(binary)], capture_output=True, text=True, timeout=90
    )
    assert result.returncode == 0, result.stderr
    completed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr

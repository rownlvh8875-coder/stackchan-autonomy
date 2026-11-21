"""Shared actual PC C++20 probe build, including explicitly supplied Windows binary."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"


@pytest.fixture(scope="module")
def probe_exe(tmp_path_factory):
    # Windows bench can reuse a locally built native probe without downloading a toolchain.
    supplied = os.environ.get("STACKCHAN_TEST_WAKE_PROBE_EXE")
    if supplied:
        path = Path(supplied)
        assert path.is_file() and not path.is_symlink()
        return path
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("Native stdin probe integration runs on Linux CI; Windows uses pinned Zig")
    binary = tmp_path_factory.mktemp("pc-wake-probe") / "wake-probe"
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
            str(BASE / "core"),
            str(TOOLS / "wake_stage1_probe.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    return binary

"""Cross-check exact SCPS framing bytes across C++20 and Python."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from scps_usb_wire import Frame, Op, encode  # noqa: E402


def test_scps_cpp_python_byte_for_byte(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "scps_interop"
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
            str(root / "tests" / "scps_usb_interop.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=90,
    )
    lines = subprocess.run(
        [str(binary)], text=True, capture_output=True, check=True, timeout=15
    ).stdout.splitlines()
    hello = bytes(range(86))
    sealed = bytes(range(0x90, 0x90 + 35))
    expected = [
        encode(Frame(Op.DEVICE_HELLO, hello)).hex(),
        encode(Frame(Op.PC_HELLO, hello)).hex(),
        encode(Frame(Op.SEALED, sealed)).hex(),
        encode(Frame(Op.COMPLETED)).hex(),
        encode(Frame(Op.STOP)).hex(),
    ]
    assert lines == expected

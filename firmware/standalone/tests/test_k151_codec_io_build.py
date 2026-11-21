"""Actual dormant port, pinned codec headers, host-only driver C ABI doubles."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
SDK = BASE / "tests/sdk_esp_codec_dev_1_6_2"


def test_pinned_codec_headers():
    proof = json.loads((SDK / "provenance.json").read_text())
    for name, expected in proof["files"].items():
        assert hashlib.sha256((SDK / name).read_bytes()).hexdigest() == expected


def test_sdk_bytes_survive_windows_git_checkout(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("Git required for checkout conversion regression")
    repo = tmp_path / "repo"
    relative = Path("firmware/standalone/tests/sdk_esp_codec_dev_1_6_2")
    (repo / relative.parent).mkdir(parents=True)
    shutil.copytree(SDK, repo / relative)
    shutil.copyfile(BASE.parents[1] / ".gitattributes", repo / ".gitattributes")
    checkout = tmp_path / "checkout"
    commands = [
        [git, "-c", "core.autocrlf=true", "init", "--quiet", str(repo)],
        [git, "-C", str(repo), "-c", "core.autocrlf=true", "add", "--all"],
        [
            git,
            "-C",
            str(repo),
            "-c",
            "core.autocrlf=true",
            "checkout-index",
            "--all",
            "--prefix=" + checkout.as_posix() + "/",
        ],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    proof = json.loads((SDK / "provenance.json").read_text())
    for name, expected in proof["files"].items():
        assert hashlib.sha256((checkout / relative / name).read_bytes()).hexdigest() == expected


@pytest.fixture(scope="module")
def port_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("codec-io") / "codec"
    sources = [BASE / "tests/k151_codec_io_test.cpp", BASE / "esp_app/main/k151_codec_port.cpp"]
    adapter = BASE / "esp_app/main/k151_bounded_i2s.cpp"
    if adapter.exists():
        sources.append(adapter)
    command = [
        compiler,
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-DCONFIG_CODEC_ES7210_SUPPORT=1",
        "-DCONFIG_CODEC_AW88298_SUPPORT=1",
    ]
    command += ["-isystem", str(SDK)]  # Unmodified vendor C anonymous unions.
    for directory in [BASE / "tests/codec_io_doubles", BASE / "core", BASE / "esp_app/main"]:
        command += ["-I", str(directory)]
    result = subprocess.run(
        command + [str(p) for p in sources] + ["-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    "mode",
    [
        "ok",
        "short",
        "overcount",
        "driver_fail",
        "clock_negative",
        "clock_backwards",
        "deadline",
        "base_lost",
        "denied",
        "invalid",
        "format_fail",
        "enable_fail",
        "disable_fail",
        "boundary",
        "reentrant",
        "write_ok",
        "write_short",
        "write_fail",
        "write_deadline",
        "halfduplex",
        "bad_rate",
        "bad_bits",
        "bad_channel",
        "bad_mask",
        "bad_mclk",
        "bad_type",
        "enable_unformatted",
        "read_unopened",
        "reformat_active",
        "reader_denied",
        "reader_bad_size",
        "null_open",
        "null_format",
        "null_enable",
        "null_read",
        "null_write",
        "info_fail",
        "ctrl_out_init_read",
        "ctrl_out_init_write",
        "ctrl_in_init_read",
        "ctrl_in_init_write",
        "ctrl_in_open_read",
        "ctrl_in_open_write",
        "ctrl_in_gain_read",
        "ctrl_in_gain_write",
        "ctrl_in_close_read",
        "ctrl_in_close_write",
        "ctrl_in_delete_read",
        "ctrl_in_delete_write",
    ],
)
def test_actual_port_fault_boundaries(port_binary, mode):
    result = subprocess.run([str(port_binary), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def control_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    folder = tmp_path_factory.mktemp("codec-control")
    obj = folder / "es7210.o"
    includes = ["-isystem", str(SDK), "-I", str(BASE / "tests/codec_io_doubles")]
    # Vendor C is compiled as C, unmodified, separately from strict owned C++.
    # Real IDF headers supply allocation declarations transitively; the tiny
    # no-hardware log double deliberately does not emulate that header tree.
    command = [compiler, "-x", "c", "-std=c11", "-O2", "-include", "stdlib.h", *includes]
    result = subprocess.run(
        command + ["-c", str(SDK / "es7210.c"), "-o", str(obj)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    binary = folder / "control"
    command = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    command += includes + ["-I", str(BASE / "esp_app/main")]
    result = subprocess.run(
        command + [str(BASE / "tests/k151_codec_control_test.cpp"), str(obj), "-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode", ["raw_read", "guard_read", "guard_write", "boundaries", "lost"])
def test_real_es7210_control_errors(control_binary, mode):
    result = subprocess.run([str(control_binary), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

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
    return _build_port(compiler, binary, BASE / "esp_app/main")


def _build_port(compiler, binary, app):
    sources = [
        BASE / "tests/k151_codec_io_test.cpp",
        app / "k151_codec_port.cpp",
        app / "k151_bounded_i2s.cpp",
        app / "k151_mic_wake_trial.cpp",
    ]
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
    for directory in [BASE / "tests/codec_io_doubles", BASE / "core", app]:
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
        "release_rx",
        "release_tx",
        "release_both",
        "release_rx_info",
        "release_bus_live_error",
        "release_bus_freed_error",
        "ctrl_out_delete_read",
        "ctrl_out_delete_write",
        "mic_only_gates",
        "mic_only_peer",
        "mic_only_ok",
        "mic_only_output",
        "mic_only_short",
        "mic_only_revoke",
        "mic_only_stop_open",
        "mic_only_stop_read",
        "mic_only_release_latched",
        "mic_only_close_failure",
        "mic_only_wakenet",
        "mic_only_wakenet_late_stop",
        "mic_only_stop_before_read",
        "mic_only_trial_ok",
        "mic_only_trial_evidence",
        "mic_only_trial_owner",
        "mic_only_trial_format",
        "mic_only_trial_stop_before",
        "mic_only_trial_reset_fail",
        "mic_only_trial_stop_on_reset",
        "mic_only_trial_stop_on_open",
        "mic_only_trial_stop_in_read",
        "mic_only_trial_stop_in_detect",
        "mic_only_trial_revoke_in_detect",
        "mic_only_trial_stop_on_close",
        "mic_only_trial_stop_on_drop",
        "mic_only_trial_short",
        "mic_only_trial_clock_backwards",
        "mic_only_trial_slow_detect",
        "mic_only_trial_model_error",
        "mic_only_trial_close_fail",
        "mic_only_trial_delete_fail",
        "mic_only_trial_wall",
        "mic_only_trial_frame_cap",
    ],
)
def test_actual_port_fault_boundaries(port_binary, mode):
    result = subprocess.run([str(port_binary), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("operation", ["read_reg", "write_reg"])
def test_aw88298_two_byte_forwarding_negative_control(tmp_path, operation):
    """An actual one-byte truncation must fail the real-port AW88298 boundary."""
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    app = tmp_path / "app"
    app.mkdir()
    for name in [
        "k151_codec_port.cpp",
        "k151_codec_port.hpp",
        "k151_bounded_i2s.cpp",
        "k151_bounded_i2s.hpp",
        "k151_codec_control.hpp",
        "k151_mic_reader.hpp",
        "k151_mic_wake_trial.hpp",
        "k151_mic_wake_trial.cpp",
        "k151_contract.hpp",
    ]:
        shutil.copyfile(BASE / "esp_app/main" / name, app / name)
    header = app / "k151_codec_control.hpp"
    source = header.read_text()
    original = f"p.base_->{operation}(p.base_, reg, len, data, size)"
    assert source.count(original) == 1
    header.write_text(source.replace(original, original.replace(", size)", ", 1)")))
    binary = _build_port(compiler, tmp_path / "codec", app)
    result = subprocess.run(
        [str(binary), "ok"], cwd=tmp_path, capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0, "truncated AW88298 register transfer escaped the fixture"
    assert "n==(out?2:1)" in result.stderr, result.stderr


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

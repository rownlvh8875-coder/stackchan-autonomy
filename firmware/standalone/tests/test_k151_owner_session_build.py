"""Exercise the K151 setup owner task using only host port doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
APP = BASE / "esp_app/main"


@pytest.fixture(scope="module")
def owner_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    folder = tmp_path_factory.mktemp("k151-owner")
    (folder / "freertos").mkdir()
    (folder / "freertos/task.h").write_text(
        "#pragma once\nusing TaskHandle_t = void*;\n"
        "TaskHandle_t xTaskGetCurrentTaskHandle();\nint xPortGetCoreID();\n"
    )
    (folder / "sdkconfig.h").write_text("#define CONFIG_ESP_CONSOLE_UART_DEFAULT 1\n")
    (folder / "psa").mkdir()
    (folder / "psa/crypto.h").write_text("#pragma once\nusing psa_key_id_t = unsigned;\n")
    binary = folder / "owner"
    args = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    for directory in (
        folder,
        BASE / "tests/lcd_io_doubles",
        BASE / "tests/codec_io_doubles",
        BASE / "core",
        APP,
    ):
        args += ["-I", str(directory)]
    ran = subprocess.run(
        args
        + [
            str(BASE / "tests/k151_owner_session_test.cpp"),
            str(APP / "k151_owner_session.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert ran.returncode == 0, ran.stderr
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "handoff",
        "hold",
        "wrong_board",
        "unverified_lcd",
        "existing_lvgl",
        "existing_bus",
        "bus_failed",
        "panel_failed",
        "view_failed",
        "head_failed",
        "no_head_touch",
        "head_read_error",
        "clock_backward",
        "clock_gap",
        "wrong_task",
        "wrong_core",
        "usb_failed",
        "usb_stop",
        "review_failed",
        "ready_frame_failed",
        "ack_failed",
        "stop_while_draining",
        "stop_after_handoff",
        "cleanup_retry",
    ],
)
def test_owner_session(owner_binary, case):
    ran = subprocess.run([str(owner_binary), case], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stderr

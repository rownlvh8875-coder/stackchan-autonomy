"""Run the display-only target entrypoint against bounded, in-memory ports."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def panel_probe(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    sdk = tmp_path_factory.mktemp("panel-probe")
    (sdk / "driver").mkdir()
    (sdk / "driver/usb_serial_jtag.h").write_text(
        "#pragma once\n#include <cstdint>\n"
        "struct usb_serial_jtag_driver_config_t { uint32_t rx_buffer_size, tx_buffer_size; };\n"
        "int usb_serial_jtag_read_bytes(void*, uint32_t, uint32_t);\n"
        "int usb_serial_jtag_driver_install(usb_serial_jtag_driver_config_t*);\n"
        "int usb_serial_jtag_driver_uninstall();\n"
        "bool usb_serial_jtag_is_driver_installed();\n"
    )
    (sdk / "esp_chip_info.h").write_text(
        "#pragma once\n#include <cstdint>\nconstexpr int CHIP_ESP32S3 = 9;\n"
        "struct esp_chip_info_t { int model; uint16_t revision; };\n"
        "void esp_chip_info(esp_chip_info_t*);\n"
    )
    (sdk / "esp_ota_ops.h").write_text(
        "#pragma once\n#include <cstdint>\n"
        "constexpr int ESP_PARTITION_TYPE_APP = 0, ESP_PARTITION_SUBTYPE_APP_OTA_1 = 17;\n"
        "struct esp_partition_t { uint32_t address, size; int type, subtype; };\n"
        "const esp_partition_t* esp_ota_get_running_partition();\n"
    )
    (sdk / "esp_random.h").write_text("#pragma once\n#include <cstdint>\nuint32_t esp_random();\n")
    binary = sdk / "panel"
    args = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    for directory in (
        sdk,
        BASE / "tests/lcd_io_doubles",
        BASE / "tests/codec_io_doubles",
        BASE / "core",
        BASE / "esp_app/main",
        BASE / "resource_bench/main",
    ):
        args += ["-I", str(directory)]
    ran = subprocess.run(
        args
        + [
            str(BASE / "tests/panel_probe_entrypoint_test.cpp"),
            str(BASE / "panel_probe/main/app_main.cpp"),
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
    ("case", "expected"),
    [
        ("ok", "DISPLAY_STOP_LATCHED"),
        ("wrong_slot", "RUNNING_LOCATION_OR_CHIP_DENIED"),
        ("wrong_subtype", "RUNNING_LOCATION_OR_CHIP_DENIED"),
        ("wrong_chip", "RUNNING_LOCATION_OR_CHIP_DENIED"),
        ("already_on_usb", "USB_SETUP_FAILED"),
        ("no_command", "NO_LOCAL_START"),
        ("wrong_nonce", "NO_LOCAL_START"),
        ("no_hello", "NO_LOCAL_START"),
        ("panel_failure", "PANEL_START_FAILED"),
        ("frame_failure", "PANEL_FRAME_FAILED"),
        ("head_fault", "HEAD_READ_OR_TIMING_FAILED"),
        ("no_head", "HOST_STOP_OR_DEADLINE"),
        ("host_stop", "HOST_STOP_OR_DEADLINE"),
        ("arm_failure", "DISPLAY_STOP_ARM_FAILED"),
        ("early_irq", "EARLY_DISPLAY_IRQ"),
        ("cleanup_failure", "DISPLAY_STOP_LATCHED"),
    ],
)
def test_panel_diagnostic(panel_probe, case, expected):
    ran = subprocess.run([str(panel_probe), case], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stderr
    events = [json.loads(line) for line in ran.stdout.splitlines() if line.startswith("{")]
    result = next(event for event in events if "result" in event)
    assert result["result"] == expected
    if "cleanup" in result:
        assert result["cleanup"] is (case != "cleanup_failure")
    if expected == "DISPLAY_STOP_LATCHED":
        assert any(event.get("probe") == "HEAD_CONFIRMED" for event in events)
        assert any(event.get("probe") == "WAIT_SCREEN_STOP" for event in events)
    assert all(not event.get("operating_admission", False) for event in events)
    assert "12345678" not in ran.stdout  # Optical code exists only in the LVGL call.

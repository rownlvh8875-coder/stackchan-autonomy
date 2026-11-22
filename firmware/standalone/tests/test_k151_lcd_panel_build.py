"""Exercise the real LVGL bridge, SPI transport and masked board I/O offline."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
APP = BASE / "esp_app/main"


@pytest.fixture(scope="module")
def lcd_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("k151-lcd") / "lcd"
    command = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    command += ["-isystem", str(BASE / "tests/sdk_esp_codec_dev_1_6_2")]
    for folder in (
        BASE / "tests/lcd_io_doubles",
        BASE / "tests/codec_io_doubles",
        BASE / "core",
        APP,
    ):
        command += ["-I", str(folder)]
    result = subprocess.run(
        command
        + [
            str(BASE / "tests/k151_lcd_panel_test.cpp"),
            str(APP / "k151_lcd_panel.cpp"),
            str(APP / "k151_setup_lvgl.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "ok",
        "cold_start",
        "cold_other_output_high",
        "cold_stop_before_release",
        "cold_stop_after_release",
        "cold_panel_read_error",
        "cold_reset_write_error",
        "cold_restore_retry",
        "cold_restore_with_foreign_output",
        "handoff_idle",
        "handoff_touch_held",
        "handoff_late_press",
        "handoff_i2c_error",
        "handoff_stopped",
        "review_ok",
        "review_held_early",
        "review_brief_or_multiple",
        "review_prompt_replaced",
        "review_gap",
        "review_clock_back",
        "review_stop",
        "review_i2c_error",
        "review_invalid_count",
        "review_lost_lock",
        "review_short_frame",
        "review_final_short_frame",
        "review_voice_existing",
        "review_voice_first",
        "review_voice_banner_failure",
        "hold",
        "wrong_bus",
        "not_requested",
        "lvgl_not_initialized",
        "wrong_panel",
        "panel_read_error",
        "wrong_pmic",
        "wrong_expander_mode",
        "wrong_reset_direction",
        "no_dma_memory",
        "spi_in_use",
        "sd_select_error",
        "sd_pin_config_error",
        "lcd_open_error",
        "lvgl_error",
        "lvgl_event_error",
        "init_spi_error",
        "initial_spi_error",
        "short_frame",
        "brightness_readback_error",
        "stop_reset",
        "stop_enabling_lamp",
        "stop_after_start",
        "sas_spi_error",
        "sas_short_frame",
    ],
)
def test_board_display_lifecycle(lcd_binary, case):
    ran = subprocess.run([str(lcd_binary), case], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stderr

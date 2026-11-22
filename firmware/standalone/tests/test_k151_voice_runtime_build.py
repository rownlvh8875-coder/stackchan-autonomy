"""Exercise the target runtime and API binding with host-only port doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
APP = BASE / "esp_app/main"


@pytest.fixture(scope="module")
def runtime_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    folder = tmp_path_factory.mktemp("k151-voice-runtime")
    (folder / "freertos").mkdir()
    (folder / "esp_event.h").write_text(
        "#pragma once\nusing esp_event_base_t = const char*;\n"
        "using esp_event_handler_instance_t = void*;\n"
    )
    (folder / "esp_netif.h").write_text("#pragma once\nstruct esp_netif_t;\n")
    (folder / "freertos/queue.h").write_text("#pragma once\nusing QueueHandle_t = void*;\n")
    (folder / "nvs.h").write_text(
        "#pragma once\n#include <cstddef>\n#include <esp_err.h>\n"
        "using nvs_handle_t = unsigned;\n"
        "enum nvs_open_mode_t { NVS_READONLY, NVS_READWRITE };\n"
        "inline constexpr esp_err_t ESP_ERR_NVS_NOT_FOUND = 0x1102;\n"
        'extern "C" {\n'
        "esp_err_t nvs_open(const char*, nvs_open_mode_t, nvs_handle_t*);\n"
        "esp_err_t nvs_get_blob(nvs_handle_t, const char*, void*, size_t*);\n"
        "esp_err_t nvs_set_blob(nvs_handle_t, const char*, const void*, size_t);\n"
        "esp_err_t nvs_commit(nvs_handle_t);\n"
        "void nvs_close(nvs_handle_t);\n"
        "}\n"
    )
    (folder / "nvs_flash.h").write_text(
        '#pragma once\n#include <esp_err.h>\nextern "C" esp_err_t nvs_flash_init();\n'
    )
    binary = folder / "runtime"
    args = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]
    args += ["-isystem", str(BASE / "tests/sdk_esp_codec_dev_1_6_2")]
    for directory in (
        folder,
        BASE / "tests/lcd_io_doubles",
        BASE / "tests/codec_io_doubles",
        BASE / "tests/idf_partition_doubles",
        BASE / "tests/sdk_esp_sr_2_4_7",
        BASE / "core",
        APP,
    ):
        args += ["-I", str(directory)]
    result = subprocess.run(
        args
        + [
            str(BASE / "tests/k151_voice_runtime_test.cpp"),
            str(APP / "k151_voice_runtime.cpp"),
            str(APP / "k151_voice_api_adapter.cpp"),
            str(APP / "k151_voice_bootstrap.cpp"),
            str(APP / "k151_display_stop.cpp"),
            str(APP / "k151_owner_setup.cpp"),
            str(APP / "nvs_port.cpp"),
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
    "scenario",
    [
        "end_to_end",
        "revoke_during_stt",
        "hold_build",
        "not_owner",
        "no_consent",
        "wrong_board",
        "no_budget",
        "stop_before_start",
        "stop_waiting",
        "bus_lost_waiting",
        "network_failure",
        "revoke_during_poll",
        "codec_failure",
        "revoke_during_codec",
        "model_failure",
        "stop_during_model",
        "low_heap_after_model",
        "bootstrap_first_turn",
        "bootstrap_existing",
        "bootstrap_hold",
        "bootstrap_unconfirmed",
        "bootstrap_manual_stop",
        "bootstrap_no_budget_scope",
        "bootstrap_missing_bus",
        "bootstrap_wrong_bus",
        "bootstrap_wrong_stop_binding",
        "bootstrap_stop_lcd_handoff_refused",
        "bootstrap_stop_irq_bad_id",
        "bootstrap_stop_irq_bad_direction",
        "bootstrap_stop_mask_write_failed",
        "bootstrap_stop_mask_readback_failed",
        "bootstrap_stop_masks_already_configured",
        "bootstrap_stop_panel_polling",
        "bootstrap_stop_probe_busy",
        "bootstrap_stop_gpio_error",
        "bootstrap_stop_arming_restore_retry",
        "bootstrap_stop_held_at_arm",
        "bootstrap_stop_timer_create",
        "bootstrap_stop_timer_start",
        "bootstrap_stop_before_budget",
        "bootstrap_stop_consent_lost_arming",
        "bootstrap_display_stop_waiting_network",
        "bootstrap_display_stop_restore_retry",
        "bootstrap_display_stop_during_stt",
        "bootstrap_display_stop_during_gpt",
        "bootstrap_display_stop_during_tts",
        "bootstrap_bus_lost_at_init",
        "bootstrap_bus_lost_during_restore",
        "bootstrap_first_denied",
        "bootstrap_nvs_init_error",
        "bootstrap_nvs_read_error",
        "bootstrap_corrupt",
        "bootstrap_revoked_at_open",
        "bootstrap_commit_error",
        "bootstrap_readback_error",
        "bootstrap_stop_at_reservation",
        "bootstrap_revoke_storage_at_stt",
        "bootstrap_wifi_revoke_owner",
        "bootstrap_wifi_revoke_storage",
        "bootstrap_usb_detached",
        "bootstrap_scopes_separate",
    ],
)
def test_runtime_owner_lifecycle(runtime_binary, scenario):
    run = subprocess.run(
        [str(runtime_binary), scenario], capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0, run.stderr

"""Exercise the target runtime and API binding with host-only port doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
APP = BASE / "esp_app/main"


def _build_runtime(folder, cjson=None):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    (folder / "freertos").mkdir()
    (folder / "psa").mkdir()
    (folder / "psa/crypto.h").write_text("#pragma once\nusing psa_key_id_t = unsigned;\n")
    (folder / "freertos/task.h").write_text(
        "#pragma once\nusing TaskHandle_t = void*;\n"
        "TaskHandle_t xTaskGetCurrentTaskHandle();\nint xPortGetCoreID();\n"
    )
    (folder / "sdkconfig.h").write_text("#define CONFIG_ESP_CONSOLE_UART_DEFAULT 1\n")
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
    realtime_sources = []
    if cjson is not None:
        include, library = cjson
        args += [
            "-DSTACKCHAN_TEST_REALTIME_WIRE",
            "-I",
            str(include),
            "-I",
            str(BASE / "tests/realtime_transport_doubles"),
        ]
        realtime_sources = [
            str(APP / "k151_voice_decode.cpp"),
            str(APP / "k151_realtime_speech.cpp"),
            library,
        ]
    result = subprocess.run(
        args
        + [
            str(BASE / "tests/k151_voice_runtime_test.cpp"),
            str(APP / "k151_voice_runtime.cpp"),
            str(APP / "k151_voice_api_adapter.cpp"),
            str(APP / "k151_voice_bootstrap.cpp"),
            str(APP / "k151_owner_session.cpp"),
            str(APP / "k151_conversation_owner.cpp"),
            str(APP / "k151_display_stop.cpp"),
            str(APP / "k151_owner_setup.cpp"),
            str(APP / "nvs_port.cpp"),
        ]
        + realtime_sources
        + ["-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.fixture(scope="module")
def runtime_binary(tmp_path_factory):
    return _build_runtime(tmp_path_factory.mktemp("k151-voice-runtime"))


@pytest.fixture(scope="module")
def realtime_runtime_binary(tmp_path_factory):
    header = Path("/usr/include/cjson/cJSON.h")
    folder = tmp_path_factory.mktemp("k151-realtime-runtime")
    if header.is_file():
        return _build_runtime(folder, (header.parent, "-lcjson"))

    # Windows can reuse the already-provisioned component from the ESP-IDF build.
    source = APP.parent / "managed_components/espressif__cjson/cJSON"
    if not (source / "cJSON.h").is_file() or not (source / "cJSON.c").is_file():
        pytest.skip("cJSON headers and local ESP-IDF cJSON source unavailable")
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    library = folder / "cJSON.o"
    compile_cjson = subprocess.run(
        [compiler, "-x", "c", "-std=c11", "-O2", "-c", str(source / "cJSON.c"), "-o", str(library)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compile_cjson.returncode == 0, compile_cjson.stderr
    return _build_runtime(folder, (source, str(library)))


def _run_runtime(binary, scenario):
    run = subprocess.run([str(binary), scenario], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr


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
        "bootstrap_one_paid_trial",
        "bootstrap_conversation_complete",
        "bootstrap_conversation_continuous",
        "bootstrap_conversation_reboot_continuous",
        "bootstrap_conversation_reboot_stop_playback",
        "bootstrap_conversation_reboot_no_budget",
        "bootstrap_conversation_save_first",
        "bootstrap_conversation_save_failed",
        "bootstrap_conversation_realtime",
        "bootstrap_conversation_stt_failure",
        "bootstrap_conversation_gpt_failure",
        "bootstrap_conversation_tts_failure",
        "bootstrap_conversation_stop",
        "bootstrap_conversation_stop_during_display",
        "bootstrap_conversation_stop_during_release",
        "bootstrap_conversation_unverified_release",
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
    _run_runtime(runtime_binary, scenario)


@pytest.mark.parametrize(
    "scenario",
    [
        "bootstrap_conversation_continuous",
        "bootstrap_conversation_reboot_continuous",
        "bootstrap_conversation_reboot_stop_playback",
        "bootstrap_conversation_tts_failure",
    ],
)
def test_runtime_realtime_wire(realtime_runtime_binary, scenario):
    _run_runtime(realtime_runtime_binary, scenario)

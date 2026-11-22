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
    binary = folder / "runtime"
    args = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    args += ["-isystem", str(BASE / "tests/sdk_esp_codec_dev_1_6_2")]
    for directory in (
        folder,
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
        "network_failure",
        "revoke_during_poll",
        "codec_failure",
        "revoke_during_codec",
        "model_failure",
        "stop_during_model",
        "low_heap_after_model",
    ],
)
def test_runtime_owner_lifecycle(runtime_binary, scenario):
    run = subprocess.run(
        [str(runtime_binary), scenario], capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0, run.stderr

"""Run isolated network/time policy checks without radio, sockets or secrets."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_network_time_guard_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    # The pinned ESP-IDF 6.1 Kconfig supplies one hour if neither file overrides it.
    refresh_ms = 3_600_000
    for name in ("sdkconfig.defaults", "sdkconfig.conversation.defaults"):
        for line in (root / "esp_app" / name).read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == "CONFIG_LWIP_SNTP_UPDATE_DELAY":
                refresh_ms = int(value)
    output = tmp_path / "network_time_guard_test"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-DTEST_SNTP_REFRESH_MS={refresh_ms}",
            "-I",
            str(root / "core"),
            str(root / "tests" / "network_time_guard_test.cpp"),
            "-o",
            str(output),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(output)], check=True, timeout=30)


def test_wifi_time_discards_queued_sync_on_route_change(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    root = Path(__file__).resolve().parents[1]
    tests = root / "tests"
    main = root / "esp_app" / "main"
    for name in (
        "esp_event.h",
        "esp_netif.h",
        "esp_netif_sntp.h",
        "esp_timer.h",
        "esp_wifi.h",
        "esp_wifi_default.h",
        "freertos/FreeRTOS.h",
        "freertos/queue.h",
        "sdkconfig.h",
    ):
        header = tmp_path / name
        header.parent.mkdir(exist_ok=True)
        header.write_text('#include "wifi_time_sdk.hpp"\n', encoding="ascii")
    output = tmp_path / "k151_wifi_time_test.exe"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            *[f"-I{directory}" for directory in (tmp_path, tests, root / "core", main)],
            str(main / "k151_wifi_time.cpp"),
            str(tests / "k151_wifi_time_test.cpp"),
            "-o",
            str(output),
        ],
        check=True,
        timeout=90,
    )
    subprocess.run([str(output)], check=True, timeout=30)

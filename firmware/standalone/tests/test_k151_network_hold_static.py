"""Compile-only invariants: no secrets/radio/SNTP startup in HOLD app_main."""

from pathlib import Path


def test_network_adapter_is_only_linked_in_hold_entrypoint():
    root = Path(__file__).resolve().parents[1]
    entry = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    sdk = (root / "esp_app" / "sdkconfig.defaults").read_text()
    wifi = (root / "esp_app" / "main" / "k151_wifi_time.cpp").read_text()

    assert "K151WifiTimePort::compiled_link_marker()" in entry
    for name in (
        "K151WifiTimePort wifi",
        "K151WifiTimePort::start(",
        "esp_wifi_start(",
        "esp_wifi_connect(",
        "esp_netif_sntp_start(",
        "esp_wifi_set_config(",
        "nvs_flash_erase(",
    ):
        assert name not in entry
    assert "WIFI_STORAGE_RAM" in wifi
    assert "init.nvs_enable = 0" in wifi
    assert "link_down_.store(true)" in wifi
    assert "!active_ || faulted_ || link_down_.load()" in wifi
    assert "esp_wifi_restore(" not in wifi
    assert "esp_wifi_set_storage(WIFI_STORAGE_FLASH)" not in wifi
    assert "CONFIG_ESP_WIFI_NVS_ENABLED=n" in sdk
    assert "sk-" not in sdk
    assert "password=" not in sdk.lower()


def test_ip_renewal_immediately_revokes_network_and_sntp_start_is_idempotent():
    root = Path(__file__).resolve().parents[1]
    src = (root / "esp_app" / "main" / "k151_wifi_time.cpp").read_text()
    header = (root / "esp_app" / "main" / "k151_wifi_time.hpp").read_text()
    assert 'admission_ready_.store(false, std::memory_order_release)' in src
    assert 'if (sntp_started_) return true;' in src
    assert "bool K151WifiTimePort::live_network_ready() const" in src
    assert "last_sync_epoch_seconds_.load(std::memory_order_acquire)" in src
    assert "last_sync_monotonic_ms_.load(std::memory_order_acquire)" in src
    assert "std::atomic_bool admission_ready_{false}" in header
    assert "std::atomic_bool active_{false}" in header

"""Static guard: building the K151 observer must not enable hardware at boot."""

from pathlib import Path


def test_hold_boot_links_only_diagnostic_markers():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    assert "K151CodecPort::compiled_link_marker()" in boot
    assert "K151ReadOnlyProbe::compiled_link_marker()" in boot
    for prohibited in (
        ".prepare(",
        ".observe_once(",
        "i2c_new_master_bus(",
        "i2s_new_channel(",
        "esp_wifi_start(",
        "servo_init(",
        "nvs_flash_erase(",
        "esp_ota_begin(",
    ):
        assert prohibited not in boot, prohibited


def test_i2c_preflight_has_no_register_configuration_writes():
    root = Path(__file__).resolve().parents[1]
    probe = (root / "esp_app" / "main" / "k151_readonly_probe.cpp").read_text()
    assert "i2c_master_transmit_receive(" in probe
    assert "i2c_master_bus_rm_device(" in probe
    assert "i2c_del_master_bus(" in probe
    assert "i2c_master_transmit(" not in probe
    assert "0xA3" in probe
    assert "kTouchVersionReg" in probe
    assert "std::atomic_bool" in probe

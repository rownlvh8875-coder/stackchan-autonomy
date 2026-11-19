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


def test_scfg_port_not_started_and_no_console_multiplex():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    usb = (root / "esp_app" / "main" / "k151_usb_scfg.cpp").read_text()
    config = (root / "esp_app" / "sdkconfig.defaults").read_text()
    assert "K151ScfgUsbPort::compiled_link_marker()" in boot
    assert "K151ScfgUsbPort::start(" not in boot
    assert "usb_serial_jtag_driver_install(" not in boot
    assert "CONFIG_ESP_CONSOLE_UART_DEFAULT=y" in config
    assert "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y" in config
    assert "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED" in usb
    assert "EnrollmentServer" in (root / "esp_app" / "main" / "k151_usb_scfg.hpp").read_text()
    assert "raw_pcm" not in usb.lower()


def test_first_use_setup_has_no_unguarded_secret_getter_or_auto_wifi_start():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    header = (root / "esp_app" / "main" / "k151_owner_setup.hpp").read_text()
    implementation = (root / "esp_app" / "main" / "k151_owner_setup.cpp").read_text()
    assert "K151LocalOwnerSetup::compiled_link_marker()" in boot
    assert "K151LocalOwnerSetup setup" not in boot
    assert "start_wifi_once(" not in boot
    assert "volatile_secrets()" not in header
    assert "network_handoff_attempted_ = true" in implementation
    assert "setup_.cancel();" in implementation
    assert "network.start(owner_.load(), input_.load()" in implementation

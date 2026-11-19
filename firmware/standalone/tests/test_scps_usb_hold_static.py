"""SCPS USB ownership and physical confirmation remain off at startup."""

from pathlib import Path


def test_encrypted_usb_port_requires_sensor_and_disjoint_scfg():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    driver = (root / "esp_app" / "main" / "k151_scps_usb.cpp").read_text()
    sensor = (root / "esp_app" / "main" / "k151_head_touch_owner.cpp").read_text()
    owner = (root / "esp_app" / "main" / "k151_owner_setup.hpp").read_text()
    cmake = (root / "esp_app" / "main" / "CMakeLists.txt").read_text()
    scfg = (root / "esp_app" / "main" / "k151_usb_scfg.cpp").read_text()
    assert "K151ScpsUsbPort::compiled_link_marker()" in boot
    assert '"k151_scps_usb.cpp"' in cmake
    assert "K151ScpsUsbPort port" not in boot
    assert "K151ScpsUsbPort::start(" not in boot
    assert "usb_serial_jtag_driver_install(" not in boot
    assert "usb_serial_jtag_is_driver_installed()" in driver
    assert "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED" in driver
    assert "KSE1" not in scfg and "SCPW" not in scfg
    assert "start_scps_final_touch(" in sensor
    assert "take_scps_final_touch(" in sensor
    assert "friend class K151ScpsUsbPort;" in owner
    assert "touch_.take_scps_final_touch(now)" in driver
    assert "pairing_.open_sealed(" in driver
    assert "setup_.confirm(now,true)" in driver
    assert driver.index("touch_.take_scps_final_touch(now)") < driver.index(
        "pairing_.open_sealed("
    )
    assert "if(state_==State::complete)return true;" in driver
    assert "setup_.stop();" in driver

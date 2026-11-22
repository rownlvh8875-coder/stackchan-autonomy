"""Guard: device HOLD image cannot activate peripherals or choose OTA slot."""

from pathlib import Path


def test_hardware_hold_is_marker_only_in_app_entrypoint():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    cmake = (root / "esp_app" / "main" / "CMakeLists.txt").read_text()
    source = (root / "esp_app" / "main" / "k151_install_hold.cpp").read_text()
    guard = (root / "core" / "hardware_hold.hpp").read_text()
    bootstrap = (root / "esp_app" / "main" / "k151_voice_bootstrap.cpp").read_text()
    assert "K151InstallHold::compiled_link_marker()" in boot
    assert '"k151_install_hold.cpp"' in cmake
    assert '"k151_voice_bootstrap.cpp"' in cmake
    assert '"k151_display_stop.cpp"' in cmake
    assert "K151DisplayStop::arm(" not in boot
    assert "K151DisplayStop::arm(board_bus_, panel_)" in bootstrap
    assert boot.count("K151VoiceBootstrap::") == 1
    assert "K151VoiceBootstrap::compiled_link_marker()" in boot
    assert "K151VoiceBootstrap " not in boot
    assert "K151OwnerSession::compiled_link_marker()" in boot
    assert "K151OwnerSession " not in boot
    assert "init_without_erase(" not in boot
    assert "restore_profile(" not in boot
    assert "!K151InstallHold::device_activation_allowed()" in bootstrap
    assert "PeripheralStopSupervisor supervisor" not in boot
    assert "esp_ota_set_boot_partition(" not in boot
    assert "esp_partition_write(" not in boot
    assert "esp_ota_begin(" not in boot
    assert "nvs_flash_erase(" not in boot
    assert "static_assert(!kHardwareActivationInHoldImage)" in source
    assert "kHardwareActivationInHoldImage = false" in guard


def test_read_only_factory_audit_cannot_install_or_access_device():
    root = Path(__file__).resolve().parents[1]
    source = (root / "tools" / "offline_factory_recovery.py").read_text()
    assert '"install_authorized": False' in source
    assert '"flash_modified": False' in source
    for forbidden in (
        "esptool",
        "serial.Serial(",
        "open_port(",
        "flash_write(",
        "esp_partition_write(",
        "nvs_flash_erase(",
    ):
        assert forbidden not in source

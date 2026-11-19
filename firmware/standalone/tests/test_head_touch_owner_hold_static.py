"""Prove that compiled K151 head touch may not run from the HOLD entrypoint."""

from pathlib import Path


def test_read_only_head_touch_not_started_from_boot():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    sensor = (root / "esp_app" / "main" / "k151_head_touch_owner.cpp").read_text()
    header = (root / "esp_app" / "main" / "k151_head_touch_owner.hpp").read_text()
    assert "K151HeadTouchOwner::compiled_link_marker()" in boot
    assert "K151HeadTouchOwner physical" not in boot
    assert "attach_readonly(" not in boot
    assert "poll_once(" not in boot
    assert "SI12T_OUTPUT1_ADDR" in sensor
    assert "i2c_master_transmit_receive(" in sensor
    assert "i2c_master_bus_add_device(" in sensor
    assert "i2c_master_bus_rm_device(" in sensor
    assert "si12t_setup(" not in boot
    assert "i2c_master_transmit(" not in sensor
    assert "sensor_preinitialized" in header
    assert "exclusive_bus_control" in header
    assert "begin_owner_setup(" in header
    assert "finish_owner_setup(" in header
    assert "setup.phase() == OwnerSetupPhase::confirm" in sensor

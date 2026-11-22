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
    assert "attach_for_setup(" not in boot
    assert "poll_once(" not in boot
    assert "SI12T_OUTPUT1_ADDR" in sensor
    assert "i2c_master_transmit_receive(" in sensor
    assert "i2c_master_bus_add_device(" in sensor
    assert "i2c_master_bus_rm_device(" in sensor
    assert "si12t_setup(" not in boot
    warm_attach = sensor.split("::attach_readonly(", 1)[1].split("::attach_for_setup(", 1)[0]
    attach_device = sensor.split("::attach_device(", 1)[1].split("::read_register(", 1)[0]
    assert "configure_pads(" not in warm_attach
    assert "write_register(" not in warm_attach + attach_device
    assert "sensor_preinitialized" in header
    assert "exclusive_bus_control" in header
    assert "begin_owner_setup(" in header
    assert "finish_owner_setup(" in header
    assert "setup.phase() == OwnerSetupPhase::confirm" in sensor


def test_only_head_touch_adapter_can_call_final_owner_confirmation():
    root = Path(__file__).resolve().parents[1]
    header = (root / "esp_app" / "main" / "k151_owner_setup.hpp").read_text()
    public_surface = header.split(" private:", 1)[0]
    assert "bool confirm(" not in public_surface
    assert "friend class K151HeadTouchOwner;" in header
    touch = (root / "esp_app" / "main" / "k151_head_touch_owner.cpp").read_text()
    assert "gesture_.take_final_confirmation" in touch
    assert "return setup.confirm(now_ms, true);" in touch

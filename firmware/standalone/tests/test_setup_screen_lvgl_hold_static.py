"""Protect boot HOLD and the absence of any credential text in the LCD bridge."""

from pathlib import Path


def test_lcd_only_linked_with_panel_and_external_lock_preconditions():
    root = Path(__file__).resolve().parents[1]
    boot = (root / "esp_app" / "main" / "app_main.cpp").read_text()
    bridge = (root / "esp_app" / "main" / "k151_setup_lvgl.cpp").read_text()
    header = (root / "esp_app" / "main" / "k151_setup_lvgl.hpp").read_text()
    assert "K151SetupLvgl::compiled_link_marker()" in boot
    assert "K151SetupLvgl view" not in boot
    assert "lv_init(" not in boot
    assert "lv_obj_create(" not in boot
    assert "lv_display_get_screen_active(" in bridge
    assert "exact_panel_verified" in bridge
    assert "lvgl_lock_held" in bridge
    assert "trusted_local_owner" in bridge
    assert "setup_screen_frame(" in bridge
    assert "lv_label_set_text(" in bridge
    assert "esp_lcd_panel_reset(" not in bridge
    assert "esp_lcd_panel_init(" not in bridge
    assert "esp_lcd_panel_draw_bitmap(" not in bridge
    assert "std::string_view api_key" not in header
    assert "std::string_view password" not in header

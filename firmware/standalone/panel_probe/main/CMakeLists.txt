set(ports "../../esp_app/main")
idf_component_register(
    SRCS "app_main.cpp"
         "${ports}/k151_lcd_panel.cpp" "${ports}/k151_head_touch_owner.cpp"
         "${ports}/k151_display_stop.cpp" "${ports}/k151_install_hold.cpp"
    INCLUDE_DIRS "${ports}" "../../core" "../../resource_bench/main"
    PRIV_REQUIRES app_update esp_driver_gpio esp_driver_i2c esp_driver_spi
                  esp_driver_usb_serial_jtag esp_hw_support esp_lcd esp_timer lvgl__lvgl
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)
target_compile_definitions(${COMPONENT_LIB} PRIVATE STACKCHAN_K151_PANEL_PROBE=1)

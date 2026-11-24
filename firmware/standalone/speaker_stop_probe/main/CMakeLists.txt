set(ports "../../esp_app/main")
idf_component_register(
    SRCS "../../mic_wake_trial/main/app_main.cpp"
         "${ports}/k151_speaker_stop_probe.cpp" "${ports}/k151_codec_port.cpp"
         "${ports}/k151_bounded_i2s.cpp" "${ports}/k151_display_stop.cpp"
         "${ports}/k151_lcd_panel.cpp" "${ports}/k151_install_hold.cpp"
    INCLUDE_DIRS "${ports}" "../../resource_bench/main" "../../core"
    PRIV_REQUIRES esp_partition spi_flash esp_driver_i2c esp_driver_i2s esp_driver_spi
                  esp_driver_gpio esp_lcd esp_driver_usb_serial_jtag esp_timer esp_hw_support
                  app_update lvgl__lvgl
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    STACKCHAN_K151_SPEAKER_PROBE=1 STACKCHAN_K151_SPEAKER_STOP_PROBE=1)

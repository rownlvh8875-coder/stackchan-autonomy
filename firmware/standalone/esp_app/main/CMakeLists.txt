idf_component_register(
    SRCS "app_main.cpp" "k151_wakenet_port.cpp" "k151_model_assets.cpp" "nvs_port.cpp" "k151_codec_port.cpp" "k151_bounded_i2s.cpp" "k151_mic_wake_trial.cpp" "k151_question_trial.cpp" "k151_mic_wake_trial_embedded.cpp" "k151_embedded_assets.cpp" "k151_readonly_probe.cpp" "k151_usb_scfg.cpp" "k151_usb_enrollment_store.cpp" "offline_voice_cycle_probe.cpp" "k151_https_voice.cpp" "k151_voice_decode.cpp" "k151_voice_api_adapter.cpp" "k151_wifi_time.cpp" "k151_owner_setup.cpp" "k151_head_touch_owner.cpp" "k151_setup_lvgl.cpp" "k151_secure_pc_setup.cpp" "k151_scps_usb.cpp" "k151_install_hold.cpp"
         "k151_voice_runtime.cpp" "k151_voice_bootstrap.cpp" "k151_display_stop.cpp" "k151_lcd_panel.cpp" "k151_owner_session.cpp"
    INCLUDE_DIRS "." "../../core"
    PRIV_REQUIRES espressif__esp-sr esp_partition spi_flash nvs_flash log heap esp_hw_support esp_driver_gpio esp_driver_i2c esp_driver_spi esp_lcd esp_driver_i2s esp_driver_usb_serial_jtag esp_http_client esp_wifi esp_netif esp_event mbedtls esp_timer espressif__cjson esp_codec_dev lvgl__lvgl
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)

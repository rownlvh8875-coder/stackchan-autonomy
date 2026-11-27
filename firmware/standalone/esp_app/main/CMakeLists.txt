set(k151_entry "app_main.cpp")
idf_build_get_property(k151_review K151_CONVERSATION_REVIEW)
if(k151_review)
    set(k151_entry "k151_conversation_main.cpp" "k151_conversation_policy.cpp")
    set(k151_pack "${CMAKE_CURRENT_LIST_DIR}/../../resource_bench/main/srmodels.bin")
    if(NOT CMAKE_BUILD_EARLY_EXPANSION)
        if(NOT EXISTS "${k151_pack}")
            message(FATAL_ERROR "The pinned WakeNet pack must be prepared before the conversation build")
        endif()
        file(SHA256 "${k151_pack}" k151_pack_sha)
        if(NOT k151_pack_sha STREQUAL "0255855e56bf72d1e072d2e0cbee4fb3ce1ac2c48f7fee6c8cd591f83e59ed95")
            message(FATAL_ERROR "Unexpected K151 conversation model pack")
        endif()
    endif()
    set(k151_embed EMBED_FILES "${k151_pack}")
    set(k151_boot_requires app_update esp_psram bootloader_support)
endif()

idf_component_register(
    SRCS ${k151_entry} "k151_wakenet_port.cpp" "k151_model_assets.cpp" "nvs_port.cpp" "k151_codec_port.cpp" "k151_bounded_i2s.cpp" "k151_mic_wake_trial.cpp" "k151_question_trial.cpp" "k151_mic_wake_trial_embedded.cpp" "k151_embedded_assets.cpp" "k151_readonly_probe.cpp" "k151_usb_scfg.cpp" "k151_usb_enrollment_store.cpp" "offline_voice_cycle_probe.cpp" "k151_https_voice.cpp" "k151_voice_decode.cpp" "k151_voice_api_adapter.cpp" "k151_wifi_time.cpp" "k151_owner_setup.cpp" "k151_head_touch_owner.cpp" "k151_setup_lvgl.cpp" "k151_secure_pc_setup.cpp" "k151_scps_usb.cpp" "k151_install_hold.cpp"
         "k151_voice_runtime.cpp" "k151_voice_bootstrap.cpp" "k151_display_stop.cpp" "k151_lcd_panel.cpp" "k151_owner_session.cpp" "k151_conversation_owner.cpp" "k151_realtime_speech.cpp" "k151_owner_credential_cipher.cpp"
    INCLUDE_DIRS "." "../../core"
    PRIV_REQUIRES espressif__esp-sr esp_partition spi_flash nvs_flash log heap esp_hw_support esp_driver_gpio esp_driver_i2c esp_driver_spi esp_lcd esp_driver_i2s esp_driver_usb_serial_jtag esp_http_client tcp_transport esp_wifi esp_netif esp_event mbedtls esp_timer espressif__cjson esp_codec_dev lvgl__lvgl ${k151_boot_requires}
    ${k151_embed}
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)
if(k151_review)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE STACKCHAN_K151_CONVERSATION_IMAGE=1)
    idf_build_get_property(k151_setup_probe K151_CONVERSATION_SETUP_PROBE)
    if(k151_setup_probe)
        target_compile_definitions(${COMPONENT_LIB} PRIVATE STACKCHAN_K151_CONVERSATION_SETUP_PROBE=1)
    endif()
    if(K151_CONVERSATION_PRIVATE_POLICY)
        configure_file("${K151_CONVERSATION_PRIVATE_POLICY}"
                       "${CMAKE_CURRENT_BINARY_DIR}/k151_private_policy.inc" COPYONLY)
        target_include_directories(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
        target_compile_definitions(${COMPONENT_LIB} PRIVATE STACKCHAN_K151_PRIVATE_POLICY=1)
    endif()
endif()

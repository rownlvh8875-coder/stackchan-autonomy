set(ports "../../esp_app/main")
idf_component_register(
    SRCS "app_main.cpp" "model_pack.cpp"
         "${ports}/k151_codec_port.cpp" "${ports}/k151_bounded_i2s.cpp"
         "${ports}/k151_mic_wake_trial.cpp" "${ports}/k151_mic_wake_trial_embedded.cpp"
         "${ports}/k151_wakenet_port.cpp" "${ports}/k151_model_assets.cpp"
         "${ports}/k151_embedded_assets.cpp"
    INCLUDE_DIRS "${ports}" "../../resource_bench/main" "../../core"
    PRIV_REQUIRES espressif__esp-sr esp_codec_dev esp_partition spi_flash
                  esp_driver_i2c esp_driver_i2s esp_driver_usb_serial_jtag
                  esp_timer esp_hw_support app_update mbedtls
    EMBED_FILES "srmodels.bin"
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)

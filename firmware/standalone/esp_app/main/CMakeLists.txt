idf_component_register(
    SRCS "app_main.cpp" "nvs_port.cpp" "k151_codec_port.cpp"
    INCLUDE_DIRS "." "../../core"
    PRIV_REQUIRES nvs_flash log esp_driver_i2c esp_driver_i2s esp_codec_dev
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)

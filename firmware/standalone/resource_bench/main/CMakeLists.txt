idf_component_register(
    SRCS "app_main.cpp" "../../esp_app/main/k151_wakenet_port.cpp"
         "../../esp_app/main/k151_embedded_assets.cpp"
    INCLUDE_DIRS "." "../../esp_app/main" "../../core"
    PRIV_REQUIRES espressif__esp-sr esp_driver_usb_serial_jtag esp_timer esp_hw_support mbedtls
    EMBED_FILES "srmodels.bin"
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)

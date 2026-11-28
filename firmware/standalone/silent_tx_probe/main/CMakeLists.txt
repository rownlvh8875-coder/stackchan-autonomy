set(ports "../../esp_app/main")
idf_component_register(
    SRCS "../../mic_wake_trial/main/app_main.cpp" "${ports}/k151_silent_tx_probe.cpp"
    INCLUDE_DIRS "${ports}" "../../resource_bench/main" "../../core"
    PRIV_REQUIRES esp_partition spi_flash esp_driver_i2s esp_driver_usb_serial_jtag
                  esp_timer esp_hw_support app_update
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)
target_compile_definitions(${COMPONENT_LIB} PRIVATE STACKCHAN_K151_SILENT_TX_PROBE=1)

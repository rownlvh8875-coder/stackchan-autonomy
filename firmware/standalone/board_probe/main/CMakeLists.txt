idf_component_register(
    SRCS "app_main.cpp" "../../esp_app/main/k151_readonly_probe.cpp"
    INCLUDE_DIRS "." "../../resource_bench/main" "../../esp_app/main" "../../core"
    PRIV_REQUIRES esp_driver_i2c esp_driver_usb_serial_jtag esp_timer esp_hw_support app_update
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)
if(K151_POWER_READBACK)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE STACKCHAN_K151_POWER_READBACK=1)
endif()

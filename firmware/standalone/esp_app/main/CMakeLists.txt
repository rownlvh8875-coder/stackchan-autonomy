idf_component_register(
    SRCS "app_main.cpp" "nvs_port.cpp"
    INCLUDE_DIRS "." "../../core"
    PRIV_REQUIRES nvs_flash log
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)

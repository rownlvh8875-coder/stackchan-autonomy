idf_component_register(SRCS "app_main.cpp" INCLUDE_DIRS "../../core" "../../esp_app/main")
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_20)

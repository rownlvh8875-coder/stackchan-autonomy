# Separate silent laboratory app. Never flash generated bootloader/table.
cmake_minimum_required(VERSION 3.16)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Exclude unused IDF services from the application dependency graph.
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(k151_resource_bench)
# Keep the lab image's promise enforceable in the actual resolved build graph.
idf_build_get_property(bench_components BUILD_COMPONENTS)
foreach(forbidden nvs_flash esp_wifi esp_http_client esp_driver_i2s)
    if(forbidden IN_LIST bench_components)
        message(FATAL_ERROR "Silent resource bench must not link ${forbidden}")
    endif()
endforeach()

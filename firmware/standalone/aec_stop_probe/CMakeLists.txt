cmake_minimum_required(VERSION 3.16)
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(k151_aec_stop_selftest)

idf_build_get_property(probe_components BUILD_COMPONENTS)
foreach(forbidden esp_driver_i2s esp_driver_i2c nvs_flash esp_wifi esp_netif esp_http_client esp_tls
                  espressif__esp-sr)
    if(forbidden IN_LIST probe_components)
        message(FATAL_ERROR "The AEC synthetic self-test must not link ${forbidden}")
    endif()
endforeach()

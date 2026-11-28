# Temporary display diagnostic. Never install the generated bootloader or table.
cmake_minimum_required(VERSION 3.16)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
option(K151_PANEL_STOP_ONLY "Build the front screen STOP-only diagnostic" OFF)
if(K151_PANEL_STOP_ONLY)
    project(k151_screen_stop_probe)
else()
    project(k151_panel_probe)
endif()
idf_build_get_property(probe_components BUILD_COMPONENTS)
# esp_lcd declares esp_driver_i2s even when only its SPI objects are used.
# The review build checks for I2S symbols in the linked ELF.
foreach(forbidden nvs_flash esp_wifi esp_http_client esp_codec_dev
                  espressif__esp_codec_dev espressif__esp-sr)
    if(forbidden IN_LIST probe_components)
        message(FATAL_ERROR "Panel probe must not link ${forbidden}")
    endif()
endforeach()

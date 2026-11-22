# ESP-IDF v6.1 (tag object fff9895c82d744c7237be8847347bdd1b07c6643)
# COMPILE ONLY. NO DEVICE FLASH/OTA/INSTALL SCRIPTS.
cmake_minimum_required(VERSION 3.16)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(stackchan_standalone_hold)

# The pinned SDK's WebSocket upgrade writer can log Authorization even at
# error level. Compile out that component's logs in this app.
idf_component_get_property(k151_tcp_transport tcp_transport COMPONENT_LIB)
target_compile_definitions(${k151_tcp_transport} PRIVATE LOG_LOCAL_LEVEL=ESP_LOG_NONE)

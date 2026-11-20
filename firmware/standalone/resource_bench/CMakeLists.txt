# Separate silent laboratory app. Never flash generated bootloader/table.
cmake_minimum_required(VERSION 3.16)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Exclude unused IDF services from the application dependency graph.
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(k151_resource_bench)

# Source overlay for ESP-IDF fff9895c. Generate into this build and keep the
# shared SDK checkout and the nvs_flash component's dependencies intact.
function(k151_fix_nvs_blob_recovery)
    idf_component_get_property(nvs_target nvs_flash COMPONENT_LIB)
    idf_component_get_property(nvs_dir nvs_flash COMPONENT_DIR)
    set(original "${nvs_dir}/src/nvs_page.cpp")
    get_target_property(sources "${nvs_target}" SOURCES)
    list(FIND sources "${original}" index)
    if(index EQUAL -1)
        message(FATAL_ERROR "K151 conversation requires the pinned nvs_flash page source")
    endif()

    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${original}")
    file(READ "${original}" content)
    string(REPLACE "\r\n" "\n" content "${content}")
    string(SHA256 source_sha "${content}")
    if(NOT source_sha STREQUAL "e77a3cb5c9baa6011df2a0cb0053d7f84a003ac1d26d0a7845beadcfaefbfd49")
        message(FATAL_ERROR "K151 NVS recovery fix requires the reviewed ESP-IDF page source")
    endif()

    # At boot the last fragment can belong to a new, unfinished blob. Match
    # its chunk index so duplicate cleanup cannot erase the committed version.
    string(REPLACE
        "findItem(item.nsIndex, item.datatype, item.key, findItemIndex, dupItem)"
        "findItem(item.nsIndex, item.datatype, item.key, findItemIndex, dupItem, item.chunkIndex)"
        content "${content}")
    set(patched "${CMAKE_BINARY_DIR}/k151_nvs_recovery/k151_nvs_page.cpp")
    file(CONFIGURE OUTPUT "${patched}" CONTENT "${content}" @ONLY NEWLINE_STYLE UNIX)
    list(REMOVE_AT sources "${index}")
    list(INSERT sources "${index}" "${patched}")
    set_property(TARGET "${nvs_target}" PROPERTY SOURCES "${sources}")
    target_include_directories("${nvs_target}" PRIVATE "${nvs_dir}/src")
endfunction()

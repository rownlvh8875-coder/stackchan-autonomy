// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>

inline constexpr uint32_t MALLOC_CAP_DMA = 1 << 3;
inline constexpr uint32_t MALLOC_CAP_8BIT = 1 << 2;
inline constexpr uint32_t MALLOC_CAP_INTERNAL = 1 << 11;
inline constexpr uint32_t MALLOC_CAP_SPIRAM = 1 << 10;
struct multi_heap_info_t {
  size_t total_free_bytes;
  size_t largest_free_block;
};
extern "C" void* heap_caps_malloc(size_t size, uint32_t caps);
extern "C" void heap_caps_free(void* ptr);
extern "C" void heap_caps_get_info(multi_heap_info_t* info, uint32_t caps);
extern "C" size_t heap_caps_get_free_size(uint32_t caps);
extern "C" size_t heap_caps_get_largest_free_block(uint32_t caps);
extern "C" size_t heap_caps_get_minimum_free_size(uint32_t caps);
extern "C" int heap_caps_monitor_local_minimum_free_size_start();
extern "C" int heap_caps_monitor_local_minimum_free_size_stop();

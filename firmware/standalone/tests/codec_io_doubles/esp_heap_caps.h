// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>

inline constexpr uint32_t MALLOC_CAP_8BIT = 1 << 2;
inline constexpr uint32_t MALLOC_CAP_INTERNAL = 1 << 11;
struct multi_heap_info_t {
  size_t total_free_bytes;
  size_t largest_free_block;
};
extern "C" void heap_caps_get_info(multi_heap_info_t* info, uint32_t caps);

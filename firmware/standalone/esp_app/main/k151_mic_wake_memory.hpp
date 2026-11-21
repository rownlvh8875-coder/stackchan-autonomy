// SPDX-License-Identifier: MIT
#pragma once

#include "audio_memory_admission.hpp"
#include <esp_heap_caps.h>

namespace stackchan::standalone {

// Reuse the existing conservative internal-heap floors for this diagnostic.
// This is an observation, not a reservation or combined voice-turn admission.
inline bool k151_mic_wake_internal_heap_available() {
  multi_heap_info_t heap{};
  heap_caps_get_info(&heap, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  return heap.total_free_bytes >= kRequiredInternalFree &&
         heap.largest_free_block >= kRequiredLargestInternalBlock &&
         heap.largest_free_block <= heap.total_free_bytes;
}

}  // namespace stackchan::standalone

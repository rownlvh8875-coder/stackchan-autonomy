// SPDX-License-Identifier: MIT
#pragma once

#include "audio_memory_admission.hpp"
#include <esp_heap_caps.h>
#include <esp_err.h>
#include <optional>

namespace stackchan::standalone {

struct BenchHeapWatermark {
  size_t internal_free_at_start = 0;
  size_t psram_free_at_start = 0;
  size_t internal_min = 0;
  size_t psram_min = 0;
};

// Only the silent bench's owner takes a local minimum measurement. The SDK
// monitor is global and must be stopped on every exit, including STOP/errors.
class BenchHeapWindow final {
 public:
  BenchHeapWindow() = default;
  BenchHeapWindow(const BenchHeapWindow&) = delete;
  BenchHeapWindow& operator=(const BenchHeapWindow&) = delete;
  ~BenchHeapWindow() {
    if (active_) (void)stop();
  }

  bool start() {
    // The SDK allocates monitor bookkeeping on start. Check the existing
    // internal-heap floors with the model already resident.
    if (active_ || heap_caps_get_free_size(kInternalCaps) < kRequiredInternalFree ||
        heap_caps_get_largest_free_block(kInternalCaps) < kRequiredLargestInternalBlock ||
        heap_caps_monitor_local_minimum_free_size_start() != ESP_OK) return false;
    active_ = true;
    reading_.internal_free_at_start = heap_caps_get_free_size(kInternalCaps);
    reading_.psram_free_at_start = heap_caps_get_free_size(kPsramCaps);
    return true;
  }

  std::optional<BenchHeapWatermark> finish() {
    if (!active_) return std::nullopt;
    reading_.internal_min = heap_caps_get_minimum_free_size(kInternalCaps);
    reading_.psram_min = heap_caps_get_minimum_free_size(kPsramCaps);
    if (!stop() || reading_.internal_free_at_start == 0 || reading_.psram_free_at_start == 0 ||
        reading_.internal_min > reading_.internal_free_at_start ||
        reading_.psram_min > reading_.psram_free_at_start) return std::nullopt;
    return reading_;
  }

 private:
  bool stop() {
    active_ = false;
    return heap_caps_monitor_local_minimum_free_size_stop() == ESP_OK;
  }

  static constexpr uint32_t kInternalCaps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  static constexpr uint32_t kPsramCaps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
  BenchHeapWatermark reading_{};
  bool active_ = false;
};

}  // namespace stackchan::standalone

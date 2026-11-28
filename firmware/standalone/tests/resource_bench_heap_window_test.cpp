// SPDX-License-Identifier: MIT
#include "bench_heap_window.hpp"
#include <cassert>

using namespace stackchan::standalone;

namespace {
constexpr uint32_t internal = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
constexpr uint32_t psram = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
size_t free_internal = 128 * 1024;
size_t largest_internal = 32 * 1024;
size_t minimum_internal = 90 * 1024;
constexpr size_t free_psram = 7 * 1024 * 1024;
constexpr size_t minimum_psram = 4 * 1024 * 1024;
bool active = false;
bool begin_fails = false;
bool end_fails = false;
int starts = 0;
int stops = 0;
int minimum_reads = 0;
}

extern "C" size_t heap_caps_get_free_size(uint32_t caps) {
  if (caps == internal) return active ? free_internal - 24 : free_internal;
  assert(active && caps == psram);
  return free_psram;
}

extern "C" size_t heap_caps_get_largest_free_block(uint32_t caps) {
  assert(!active && caps == internal);
  return largest_internal;
}

extern "C" size_t heap_caps_get_minimum_free_size(uint32_t caps) {
  assert(active && (caps == internal || caps == psram));
  ++minimum_reads;
  return caps == internal ? minimum_internal : minimum_psram;
}

extern "C" int heap_caps_monitor_local_minimum_free_size_start() {
  assert(!active);
  ++starts;
  if (begin_fails) return ESP_FAIL;
  active = true;
  return ESP_OK;
}

extern "C" int heap_caps_monitor_local_minimum_free_size_stop() {
  assert(active);
  ++stops;
  active = false;
  return end_fails ? ESP_FAIL : ESP_OK;
}

int main() {
  {
    BenchHeapWindow window;
    assert(!window.finish() && !active);
    assert(window.start() && active && !window.start());
    const auto reading = window.finish();
    assert(reading && !active && !window.finish());
    assert(reading->internal_free_at_start == free_internal - 24);
    assert(reading->psram_free_at_start == free_psram);
    assert(reading->internal_min == minimum_internal);
    assert(reading->psram_min == minimum_psram);
    assert(starts == 1 && stops == 1 && minimum_reads == 2);
  }
  {
    BenchHeapWindow early_exit;
    assert(early_exit.start() && active);
  }
  assert(!active && starts == 2 && stops == 2 && minimum_reads == 2);
  {
    BenchHeapWindow denied;
    --free_internal;
    assert(!denied.start());
    ++free_internal;
    --largest_internal;
    assert(!denied.start());
    ++largest_internal;
    assert(starts == 2 && stops == 2);
    begin_fails = true;
    assert(!denied.start() && !denied.finish());
    begin_fails = false;
  }
  assert(!active && starts == 3 && stops == 2);
  {
    BenchHeapWindow invalid;
    minimum_internal = free_internal + 1;
    assert(invalid.start() && !invalid.finish());
    minimum_internal = 90 * 1024;
    assert(!active && starts == 4 && stops == 3 && minimum_reads == 4);
  }
  {
    BenchHeapWindow stop_error;
    end_fails = true;
    assert(stop_error.start() && !stop_error.finish() && !stop_error.finish());
  }
  assert(!active && starts == 5 && stops == 4 && minimum_reads == 6);
}

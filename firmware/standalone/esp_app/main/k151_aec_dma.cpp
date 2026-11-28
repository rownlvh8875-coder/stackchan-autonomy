// SPDX-License-Identifier: MIT
#include "k151_aec_dma.hpp"
#include "k151_aec_stop_probe.hpp"

#include <esp_attr.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>

namespace stackchan::standalone {
namespace {
using Probe = K151AecStopProbe;
constexpr unsigned kRing = 16;
constexpr auto kFrames = Probe::kFramesPerBlock;
constexpr auto kWords = kFrames * Probe::kSlots;
struct Block {
  int64_t time;
  int16_t samples[kFrames];
};
DRAM_ATTR Block ring[kRing];
DRAM_ATTR portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
DRAM_ATTR unsigned produced = 0, consumed = 0;
DRAM_ATTR bool recording = false, attempted = false, invalid = false;

bool IRAM_ATTR receive(i2s_chan_handle_t, i2s_event_data_t* event, void*) {
  const auto now = esp_timer_get_time();
  const bool safe_buffer = event && event->dma_buf && event->size == kWords * sizeof(int16_t);
  volatile int16_t* data = safe_buffer ? static_cast<int16_t*>(event->dma_buf) : nullptr;
  portENTER_CRITICAL_ISR(&lock);
  if (recording && !invalid) {
    if (!data || now < 0 || produced - consumed >= kRing ||
        produced >= Probe::kMaxFrames / kFrames) {
      invalid = true;
    } else {
      auto& block = ring[produced % kRing];
      block.time = now;
      for (unsigned i = 0; i < kFrames; ++i)
        block.samples[i] = data[i * Probe::kSlots + Probe::kReferenceSlot];
      ++produced;
    }
  }
  portEXIT_CRITICAL_ISR(&lock);
  if (data) {
    for (unsigned i = 0; i < kWords; ++i) data[i] = 0;
  }
  return false;
}
}

bool attach_k151_aec_dma(i2s_chan_handle_t rx) {
  i2s_event_callbacks_t callbacks{};
  callbacks.on_recv = receive;
  return i2s_channel_register_event_callback(rx, &callbacks, nullptr) == ESP_OK;
}

bool begin_k151_aec_dma() {
  portENTER_CRITICAL(&lock);
  const bool ok = !attempted;
  attempted = true;
  recording = ok;
  portEXIT_CRITICAL(&lock);
  return ok;
}

bool k151_aec_dma_faulted() {
  portENTER_CRITICAL(&lock);
  const bool result = invalid;
  portEXIT_CRITICAL(&lock);
  return result;
}

bool take_k151_aec_block(std::span<int16_t> destination, uint32_t& first_frame, int64_t& eof_us) {
  if (destination.size() != kWords) return false;
  wipe_pcm(destination);
  portENTER_CRITICAL(&lock);
  const bool ready = recording && !invalid && consumed != produced;
  if (ready) {
    auto& block = ring[consumed % kRing];
    eof_us = block.time;
    first_frame = consumed * kFrames;
    for (unsigned i = 0; i < kFrames; ++i)
      destination[i * Probe::kSlots + Probe::kReferenceSlot] = block.samples[i];
    wipe_pcm(block.samples);
    ++consumed;
  }
  portEXIT_CRITICAL(&lock);
  return ready;
}

void end_k151_aec_dma() {
  portENTER_CRITICAL(&lock);
  recording = false;
  portEXIT_CRITICAL(&lock);
  // No producer can write the ring after recording is cleared under the lock.
  for (auto& block : ring) wipe_pcm(block.samples);
}

}  // namespace stackchan::standalone

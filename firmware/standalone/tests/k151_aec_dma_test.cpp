// SPDX-License-Identifier: MIT
#include "k151_aec_dma.hpp"
#include "k151_aec_timeline.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <string_view>

using namespace stackchan::standalone;
namespace {
using Probe = K151AecStopProbe;
using PcmBlock = std::array<int16_t, Probe::kFramesPerBlock * Probe::kSlots>;
i2s_isr_callback_t capture = nullptr;
int64_t time_us = 0;

void push(PcmBlock& buffer, size_t size) {
  i2s_event_data_t event{buffer.data(), size};
  time_us += 10'000;
  assert(capture && !capture(nullptr, &event, nullptr));
  if (size == sizeof(buffer))
    assert(std::ranges::all_of(buffer, [](auto sample) { return sample == 0; }));
}

void offer(size_t size = 1920) {
  PcmBlock buffer{};
  for (size_t i = 0; i < buffer.size(); i += 4) {
    buffer[i] = 32767; // Microphone decoy.
    buffer[i + 1] = 37;
    buffer[i + 2] = -123;
    buffer[i + 3] = 78;
  }
  push(buffer, size);
}

void check_aligned_cutoff() {
  Probe analyzer;
  K151AecTimeline timeline;
  offer(); // DMA before START is discarded.
  assert(begin_k151_aec_dma());
  constexpr uint32_t kInjectedCutoff = 1'128;
  for (uint32_t origin = 0; origin < 2'400; origin += Probe::kFramesPerBlock) {
    PcmBlock source{}, destination{};
    for (uint32_t i = 0; i < Probe::kFramesPerBlock; ++i) {
      source[i * Probe::kSlots] = 32767; // Decoy remains loud after STOP.
      const auto frame = origin + i;
      if (frame >= 720 && frame < kInjectedCutoff)
        source[i * Probe::kSlots + Probe::kReferenceSlot] = frame % 24 < 12 ? 800 : -800;
    }
    push(source, sizeof(source));
    uint32_t first{};
    int64_t eof{};
    assert(take_k151_aec_block(destination, first, eof) && first == origin);
    assert(timeline.accept(first, eof));
    if (first == 720) assert(analyzer.begin_tone(60'720));
    if (first == 960) {
      auto stop = timeline.stop_bracket(55'000);
      assert(stop && stop->before_us == 50'000 && stop->after_us == 60'000);
      assert(stop->first_frame == 960 && stop->end_frame == 1'200);
      assert(analyzer.mark_stop(stop->first_frame));
    }
    assert(analyzer.observe(first, destination));
  }
  auto cutoff = analyzer.cutoff();
  assert(cutoff && cutoff->first_possible_frame == 1'104 && cutoff->quiet_by_frame == 1'152);
  assert(!k151_aec_dma_faulted());
  end_k151_aec_dma();
}
}

extern "C" int64_t esp_timer_get_time() { return time_us; }
extern "C" esp_err_t i2s_channel_register_event_callback(
    i2s_chan_handle_t, const i2s_event_callbacks_t* callbacks, void*) {
  assert(!callbacks->on_sent);
  capture = callbacks->on_recv;
  return ESP_OK;
}

int main(int argc, char** argv) {
  assert(attach_k151_aec_dma(nullptr)); // Host stub supplies the callback.
  if (argc > 1 && std::string_view(argv[1]) == "cutoff") {
    check_aligned_cutoff();
    return 0;
  }
  offer(); // No collection before enable.
  std::array<int16_t, 960> copy{};
  uint32_t first{};
  int64_t eof{};
  assert(!take_k151_aec_block(copy, first, eof));
  assert(begin_k151_aec_dma());
  offer();
  assert(take_k151_aec_block(copy, first, eof) && first == 0 && eof == 20'000);
  for (size_t i = 0; i < copy.size(); ++i) assert(copy[i] == (i % 4 == 1 ? 37 : 0));
  assert(!take_k151_aec_block(copy, first, eof));
  assert(std::ranges::all_of(copy, [](auto sample) { return sample == 0; }));
  if (argc == 1) {
    for (unsigned i = 0; i < 17; ++i) offer();
  } else {
    offer(8); // Short descriptor is invalid, not a quiet event.
  }
  assert(k151_aec_dma_faulted() && !take_k151_aec_block(copy, first, eof));
  end_k151_aec_dma();
  offer();
  assert(!begin_k151_aec_dma());
  assert(!take_k151_aec_block(copy, first, eof));
}

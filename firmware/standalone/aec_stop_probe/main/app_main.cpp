// SPDX-License-Identifier: MIT
#include "k151_aec_stop_probe.hpp"
#include "k151_probe_tone.hpp"

#include <array>
#include <cstdio>

namespace {
using Probe = stackchan::standalone::K151AecStopProbe;
constexpr auto tone = stackchan::standalone::k151_probe_tone<Probe::kFramesPerBlock * 3>();

std::optional<Probe::Cutoff> synthetic_cutoff() {
  constexpr uint32_t baseline_frames = 720;
  constexpr uint32_t stop_frame = 960;
  constexpr uint32_t silence_starts = stop_frame + 48;
  std::array<int16_t, Probe::kFramesPerBlock * Probe::kSlots> block{};
  Probe probe;
  for (uint32_t first = 0; first < 2'160; first += Probe::kFramesPerBlock) {
    if (first == baseline_frames && !probe.begin_tone(baseline_frames + 60'000))
      return std::nullopt;
    if (first == stop_frame && !probe.mark_stop(stop_frame)) return std::nullopt;
    for (uint32_t frame = 0; frame < Probe::kFramesPerBlock; ++frame) {
      const auto sample = tone[Probe::kFramesPerBlock + frame];
      block[frame * Probe::kSlots] = sample; // Deliberate decoy for the reference-lane check.
      const auto index = first + frame;
      block[frame * Probe::kSlots + Probe::kReferenceSlot] =
          index >= baseline_frames && index < silence_starts ? sample : 0;
    }
    if (!probe.observe(first, block)) return std::nullopt;
  }
  const auto cutoff = probe.cutoff();
  if (!cutoff || cutoff->first_possible_frame > silence_starts ||
      cutoff->quiet_by_frame < silence_starts)
    return std::nullopt;
  return cutoff;
}
}

extern "C" void app_main() {
  std::puts("K151_AEC_STOP_SYNTHETIC_ONLY_HOLD");
  const auto result = synthetic_cutoff();
  if (!result) {
    std::puts("{\"aec_selftest\":\"failed\",\"hardware_observed\":false}");
    return;
  }
  std::printf("{\"aec_selftest\":\"passed\",\"sample_rate_hz\":%u,"
              "\"stop_frame\":%u,\"first_possible_frame\":%u,\"quiet_by_frame\":%u,"
              "\"hardware_observed\":false}\n",
              unsigned(Probe::kSampleRate), unsigned(result->stop_frame),
              unsigned(result->first_possible_frame), unsigned(result->quiet_by_frame));
}

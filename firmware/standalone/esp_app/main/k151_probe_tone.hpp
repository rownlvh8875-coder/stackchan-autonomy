// SPDX-License-Identifier: MIT
#pragma once

#include "pcm_chunk_guard.hpp"
#include <array>

namespace stackchan::standalone {
template <size_t Samples>
constexpr std::array<int16_t, Samples> k151_probe_tone() {
  constexpr std::array<int16_t, 24> wave{
      0, 1060, 2048, 2896, 3547, 3956, 4096, 3956, 3547, 2896, 2048, 1060,
      0, -1060, -2048, -2896, -3547, -3956, -4096, -3956, -3547, -2896, -2048, -1060};
  std::array<int16_t, Samples> pcm{};
  for (size_t i = 0; i < pcm.size(); ++i) {
    const auto ramp = std::min({i, pcm.size() - i - 1, kPcmOutputChunkSamples});
    pcm[i] = wave[i % wave.size()] * static_cast<int>(ramp) /
             static_cast<int>(kPcmOutputChunkSamples);
  }
  return pcm;
}
} // namespace stackchan::standalone

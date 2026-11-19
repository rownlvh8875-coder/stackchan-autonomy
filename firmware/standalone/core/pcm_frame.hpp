// SPDX-License-Identifier: MIT
// Host-testable bounded audio frames for future K151 24kHz codec adapter.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>

namespace stackchan::standalone {
constexpr size_t kPcmFramesPerTenMs = 240;

// Two interleaved PCM16 lanes: channel 0 mic, channel 1 reference. Source-
// derived channel order is NOT yet verified against the user's K151.
inline bool extract_k151_mic0(std::span<const int16_t> mic_and_reference,
                              std::span<int16_t> mono) {
  if (mono.empty() || mono.size() > kPcmFramesPerTenMs ||
      mic_and_reference.size() != mono.size() * 2) {
    std::fill(mono.begin(), mono.end(), 0);
    return false;
  }
  for (size_t i = 0; i < mono.size(); ++i) mono[i] = mic_and_reference[i * 2];
  return true;
}

inline bool valid_pcm_playback(std::span<const int16_t> mono) {
  return !mono.empty() && mono.size() <= kPcmFramesPerTenMs;
}
}  // namespace stackchan::standalone

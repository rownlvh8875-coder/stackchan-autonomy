// SPDX-License-Identifier: MIT
// EXPERIMENT ONLY: energy-based speech-region trimming before MFCC.
// Not validated on humans; NEVER invoked by K151 esp_app or hardware HOLD.
// Deterministic, <= 3s 24kHz mono PCM16; rejects insufficiently distinct voice.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {

inline constexpr size_t kTrimFrame24k = 240; // 10 milliseconds
inline constexpr size_t kTrimMaxPcm24k = 72000;
inline constexpr size_t kTrimMinPcm24k = 2400;
inline constexpr size_t kTrimPaddingFrames = 4; // 40ms context per side

inline std::optional<std::vector<int16_t>> offline_trim_speech_24k(
    std::span<const int16_t> pcm) {
  if (pcm.size() < kTrimMinPcm24k || pcm.size() > kTrimMaxPcm24k)
    return std::nullopt;
  const size_t frame_count = (pcm.size() + kTrimFrame24k - 1) / kTrimFrame24k;
  if (frame_count < 10 || frame_count > 300) return std::nullopt;
  std::vector<float> energy(frame_count, 0.f);
  for (size_t f = 0; f < frame_count; ++f) {
    const size_t first = f * kTrimFrame24k;
    const size_t last = std::min(first + kTrimFrame24k, pcm.size());
    double sum = 0;
    for (size_t i = first; i < last; ++i) {
      const float s = static_cast<float>(pcm[i]) / 32768.f;
      sum += static_cast<double>(s) * s;
    }
    energy[f] = static_cast<float>(std::sqrt(sum / (last - first)));
  }

  auto sorted = energy;
  std::sort(sorted.begin(), sorted.end());
  const float floor = sorted[sorted.size() / 5]; // 20th percentile, not a VAD
  const float peak = sorted.back();
  if (!std::isfinite(floor) || !std::isfinite(peak) || peak < 0.01f)
    return std::nullopt;
  // Fail closed when background is too close to voiced energy.
  if (floor > 0.35f * peak) return std::nullopt;
  const float threshold = std::max(floor * 2.5f, peak * 0.10f);
  size_t first_active = frame_count, last_active = 0, active_count = 0;
  for (size_t i = 0; i < frame_count; ++i) {
    if (energy[i] > threshold) {
      first_active = std::min(first_active, i);
      last_active = std::max(last_active, i);
      ++active_count;
    }
  }
  if (first_active == frame_count || active_count < 7)
    return std::nullopt; // no enough voiced frames, reject without fallbacks

  const size_t first_frame = first_active > kTrimPaddingFrames
      ? first_active - kTrimPaddingFrames : 0;
  const size_t last_frame = std::min(
      last_active + kTrimPaddingFrames + 1, frame_count);
  const size_t first_sample = first_frame * kTrimFrame24k;
  const size_t end_sample = std::min(last_frame * kTrimFrame24k, pcm.size());
  if (end_sample - first_sample < kTrimMinPcm24k)
    return std::nullopt;
  return std::vector<int16_t>(
      pcm.begin() + first_sample, pcm.begin() + end_sample);
}

} // namespace stackchan::standalone

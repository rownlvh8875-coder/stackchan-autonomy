// SPDX-License-Identifier: MIT
// Host offline tools only: default is bitwise-identical existing MFCC feature.
// An opt-in compile flag activates experimental energy trimming; no firmware
// changes and no automatic production wake threshold changes.
#pragma once

#include "wake_features.hpp"
#ifdef STACKCHAN_EXPERIMENTAL_WAKE_TRIM
#include "offline_wake_trim.hpp"
#endif

#include <optional>
#include <span>

namespace stackchan::standalone {

inline std::optional<WakeFeature> offline_wake_extract(
    std::span<const int16_t> pcm) {
#ifdef STACKCHAN_EXPERIMENTAL_WAKE_TRIM
  auto trimmed = offline_trim_speech_24k(pcm);
  if (!trimmed) return std::nullopt;
  return wake_mfcc_from_24k(*trimmed);
#else
  return wake_mfcc_from_24k(pcm);
#endif
}

} // namespace stackchan::standalone

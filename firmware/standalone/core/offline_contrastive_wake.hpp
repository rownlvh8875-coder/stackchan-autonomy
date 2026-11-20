// SPDX-License-Identifier: MIT
// Host-only research policy; NOT enabled in K151 ESP-IDF or production HOLD.
// Reject a wake match when a declared nonwake calibration feature is closer.
#pragma once
#include "offline_wake_feature.hpp"

#include <algorithm>
#include <cmath>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {

inline constexpr size_t kContrastiveMaxNegatives = 48;

// Development-only scalar: explicit, fixed before any NEW validation WAVs.
// This is a heuristic not independently calibrated for human speech.
inline constexpr float kContrastiveNonwakeMargin = 2.0f;

struct ContrastiveWakeDecision {
  bool accepted = false;
  float best_wake_distance = 0.f;
  float nearest_nonwake_distance = 0.f;
};

inline std::optional<ContrastiveWakeDecision> offline_contrastive_wake(
    const WakeProfile& positive, std::span<const WakeFeature> negative_features,
    const WakeFeature& probe) {
  if (positive.templates.empty() || positive.templates.size() > 3 ||
      positive.limit_q8 == 0 || negative_features.size() < 10 ||
      negative_features.size() > kContrastiveMaxNegatives)
    return std::nullopt;

  float best_wake = std::numeric_limits<float>::infinity();
  float nearest_nonwake = std::numeric_limits<float>::infinity();
  for (const auto& item : positive.templates)
    best_wake = std::min(best_wake, wake_dtw_distance(item, probe));
  for (const auto& item : negative_features)
    nearest_nonwake = std::min(nearest_nonwake, wake_dtw_distance(item, probe));
  if (!std::isfinite(best_wake) || !std::isfinite(nearest_nonwake))
    return std::nullopt;

  return ContrastiveWakeDecision{
    positive.accepts(probe) &&
        nearest_nonwake > best_wake * kContrastiveNonwakeMargin,
    best_wake, nearest_nonwake
  };
}
} // namespace stackchan::standalone

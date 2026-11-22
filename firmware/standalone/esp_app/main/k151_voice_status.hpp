// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>

namespace stackchan::standalone {
// Local state only. This interface never carries conversation or account data.
enum class K151VoiceStatus : uint8_t {
  connecting, listening, question, processing, playing, returning, trial_finished
};
} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>

namespace stackchan::standalone {
// Local state only. This interface never carries conversation or account data.
enum class K151VoiceStatus : uint8_t {
  connecting, listening, question, transcribing, generating, synthesizing,
  playing, returning, trial_finished, reboot_ready, checking_budget, budget_verified
};
} // namespace stackchan::standalone

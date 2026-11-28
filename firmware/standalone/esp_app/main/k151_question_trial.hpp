// SPDX-License-Identifier: MIT
#pragma once

#include "k151_mic_only_evidence.hpp"
#include <atomic>
#include <cstddef>

namespace stackchan::standalone {

inline constexpr size_t kK151WakeOnlyObservationFrames = 75; // 1.5s of 20ms PCM frames.

enum class K151QuestionTrialMode { standard, wake_only_control };

enum class K151QuestionTrialResult {
  not_run, stopped, memory_denied, prepare_failed, open_failed, clock_fault,
  read_failed, no_endpoint, endpoint, release_failed, quiet_timeout,
};

struct K151QuestionTrialDiagnostic {
  K151QuestionTrialResult result = K151QuestionTrialResult::not_run;
  bool codec_cleanup_unverified = false;
};

// Caller owns one local trial and provides board/RX ownership evidence and a cue.
K151QuestionTrialDiagnostic run_k151_question_trial(
    const std::atomic_bool& owner, const std::atomic_bool& stop,
    const K151MicOnlyEvidence& evidence, void (*cue)(),
    K151QuestionTrialMode mode = K151QuestionTrialMode::standard);

}  // namespace stackchan::standalone

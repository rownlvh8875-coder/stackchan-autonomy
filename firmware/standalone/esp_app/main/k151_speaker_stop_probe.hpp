// SPDX-License-Identifier: MIT
#pragma once

#include "k151_mic_only_evidence.hpp"
#include <atomic>

namespace stackchan::standalone {
struct K151SpeakerStopCue {
  std::atomic_bool pending{false};
  std::atomic_bool sent{false};
};

void report_k151_speaker_stop_probe(const std::atomic_bool& owner,
    K151AudioBoardEvidence evidence, K151SpeakerStopCue& cue);
} // namespace stackchan::standalone

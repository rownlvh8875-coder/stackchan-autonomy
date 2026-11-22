// SPDX-License-Identifier: MIT
#pragma once
#include "k151_mic_only_evidence.hpp"
#include <atomic>

namespace stackchan::standalone {

enum class K151SpeakerProbeResult {
  denied, stopped, codec_prepare_failed, clock_fault, amplifier_start_failed,
  transfer_failed, mute_confirmation_failed, cleanup_failed, observed,
};

// This is linked only into the separate TX-only synthetic speaker image.
K151SpeakerProbeResult run_k151_speaker_probe(const std::atomic_bool& owner,
    const std::atomic_bool& stop, K151AudioBoardEvidence evidence);

} // namespace stackchan::standalone

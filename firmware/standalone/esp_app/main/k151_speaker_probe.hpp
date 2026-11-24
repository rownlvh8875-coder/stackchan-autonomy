// SPDX-License-Identifier: MIT
#pragma once
#include "k151_mic_only_evidence.hpp"
#include "k151_speaker_startup_stage.hpp"
#include <atomic>

namespace stackchan::standalone {

enum class K151SpeakerProbeResult {
  denied, stopped, codec_prepare_failed, clock_fault, amplifier_start_failed,
  transfer_failed, mute_confirmation_failed, cleanup_failed, observed,
};

struct K151SpeakerProbeReport {
  K151SpeakerProbeResult result;
  K151SpeakerStartupDiagnostic startup{};
};

// This is linked only into the separate TX-only synthetic speaker image.
K151SpeakerProbeReport run_k151_speaker_probe(const std::atomic_bool& owner,
    const std::atomic_bool& stop, K151AudioBoardEvidence evidence);
const char* speaker_startup_stage_name(K151SpeakerStartupStage stage);
const char* speaker_clock_wait_exit_name(K151ClockWaitExit reason);
const char* speaker_clock_wait_sample_name(K151ClockWaitSample sample);

} // namespace stackchan::standalone

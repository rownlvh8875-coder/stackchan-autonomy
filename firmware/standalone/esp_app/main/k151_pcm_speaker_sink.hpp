// SPDX-License-Identifier: MIT
// Dormant K151 PCM sink for a future owner-approved audio lifecycle.
// This class is NEVER constructed by the HOLD firmware entrypoint.
#pragma once

#include "k151_codec_port.hpp"
#include "offline_voice_cycle.hpp"
#include "pcm_frame.hpp"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <esp_timer.h>
#include <span>

namespace stackchan::standalone {

// Use only underneath GuardedVoiceSpeaker and a separately reviewed
// AudioGuard/codec setup. PCM16 mono 24kHz is a REQUIRED upstream contract.
// Synchronous codec writes do not prove physical output timing or hard STOP.
class K151PcmSpeakerSink final : public VoiceSpeakerPort {
 public:
  K151PcmSpeakerSink(K151CodecPort& codec, const std::atomic_bool& stop,
                     const std::atomic_bool& consent)
      : codec_(codec), stop_(stop), consent_(consent) {}

  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,
                                  uint64_t started_ms) override {
    if (!codec_.prepared() || stop_.load() || !consent_.load() ||
        pcm.empty() || pcm.size() > OfflineVoiceCycle::kMaxSynthFrames)
      return {};
    for (size_t pos = 0; pos < pcm.size();) {
      if (stop_.load() || !consent_.load() || !codec_.prepared())
        return {};
      const size_t count = std::min(kPcmFramesPerTenMs, pcm.size() - pos);
      if (!codec_.play_mono_24k(pcm.subspan(pos, count))) return {};
      pos += count;
    }
    if (stop_.load() || !consent_.load()) return {};
    // Must share this timebase with the calling session's monotonic_ms.
    const int64_t now_us = esp_timer_get_time();
    if (now_us < 0 || static_cast<uint64_t>(now_us / 1000) < started_ms)
      return {};
    return {true, static_cast<uint64_t>(now_us / 1000)};
  }

 private:
  K151CodecPort& codec_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
};

} // namespace stackchan::standalone

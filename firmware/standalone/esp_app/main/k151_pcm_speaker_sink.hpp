// SPDX-License-Identifier: MIT
// Dormant K151 PCM sink for a future owner-approved audio lifecycle.
// This class is NEVER constructed by the HOLD firmware entrypoint.
#pragma once

#include "k151_codec_port.hpp"
#include "offline_voice_cycle.hpp"
#include "pcm_chunk_guard.hpp"

#include <optional>
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
    // Codec remains hard-disabled in the factory-incompatible HOLD image.
    if (!codec_.prepared()) return {};
    // The caller MUST use the same esp_timer-based monotonic millisecond
    // clock for started_ms; no conversion from UTC or another timer.
    const auto finished = stream_pcm_chunks_guarded(
        pcm, started_ms, stop_, consent_,
        [this](std::span<const int16_t> chunk) {
          return codec_.prepared() && codec_.play_mono_24k(chunk);
        },
        []() -> std::optional<uint64_t> {
          const int64_t now_us = esp_timer_get_time();
          if (now_us < 0) return std::nullopt;
          return static_cast<uint64_t>(now_us / 1000);
        });
    if (!finished) return {};
    return {true, *finished};
  }

 private:
  K151CodecPort& codec_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
};

} // namespace stackchan::standalone

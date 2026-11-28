// SPDX-License-Identifier: MIT
// Single-threaded guarded playback; no GPIO/I2S or audio driver in this file.
#pragma once

#include "audio_guard.hpp"
#include "offline_voice_cycle.hpp"

#include <atomic>
#include <cstdint>
#include <functional>
#include <optional>
#include <span>
#include <utility>

namespace stackchan::standalone {

// Wrap a PCM sink whose caller already verified 24kHz mono PCM16 and clock
// source. The sink is not permitted to manage amplifier/microphone power.
// Requires serialized AudioGuard calls; STOP cannot interrupt a blocked sink
// without independent hardware-side cancellation.
class GuardedVoiceSpeaker final : public VoiceSpeakerPort {
 public:
  GuardedVoiceSpeaker(AudioGuard& guard, VoiceSpeakerPort& sink,
                      const std::atomic_bool& stop,
                      const std::atomic_bool& owner_consent,
                      std::atomic_bool& speaker_busy,
                      std::function<std::optional<uint64_t>()> completion_clock = {})
      : guard_(guard), sink_(sink), stop_(stop), consent_(owner_consent),
        busy_(speaker_busy), completion_clock_(std::move(completion_clock)) {}

  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,
                                 uint64_t started_ms) override {
    // Deny input before any amp/codec command or lock acquisition.
    if (latched_ || stop_.load() || !consent_.load() ||
        guard_.state() != AudioState::idle || guard_.stopped() ||
        pcm.empty() || pcm.size() > OfflineVoiceCycle::kMaxSynthFrames)
      return {};
    bool expected = false;
    if (!busy_.compare_exchange_strong(expected, true)) return {};
    // Recheck after taking the playback lease to avoid a consent/STOP race.
    if (stop_.load() || !consent_.load() || !guard_.playback_begin())
      return stop_and_latch();
    if (stop_.load() || !consent_.load()) return stop_and_latch();

    // The sink MUST check STOP between each hardware block. Its return is
    // not sufficient proof of DMA drain; AudioGuard handles drain+mute.
    VoicePlaybackResult result = sink_.play_pcm24k(pcm, started_ms);
    if (stop_.load() || !consent_.load() || !result.complete ||
        result.finished_ms < started_ms)
      return stop_and_latch();

    if (!guard_.playback_end() || stop_.load() || !consent_.load()) return stop_and_latch();
    // On the device, cooldown starts after verified amplifier standby. The
    // sink's timestamp covers the I2S transfer only.
    if (completion_clock_) {
      const auto finished = completion_clock_();
      if (!finished || *finished < result.finished_ms) return stop_and_latch();
      result.finished_ms = *finished;
    }
    if (stop_.load() || !consent_.load()) return stop_and_latch();
    busy_.store(false);
    return result;
  }

  bool latched() const { return latched_; }

 private:
  VoicePlaybackResult stop_and_latch() {
    latched_ = true;
    guard_.stop();  // Best-effort immediate mic/amp mute; no false PASS.
    // Keep busy latched until independent owner-controlled restoration.
    // This instance intentionally has no reset or retry path.
    return {};
  }

  AudioGuard& guard_;
  VoiceSpeakerPort& sink_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
  std::atomic_bool& busy_;
  std::function<std::optional<uint64_t>()> completion_clock_;
  bool latched_ = false;
};

} // namespace stackchan::standalone

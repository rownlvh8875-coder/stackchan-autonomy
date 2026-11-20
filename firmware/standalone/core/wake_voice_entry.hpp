// SPDX-License-Identifier: MIT
// Offline glue: enrolled wake features -> session -> bounded voice cycle.
// No microphone, VAD, network transport, or on-device speaker is started here.
#pragma once

#include "offline_voice_cycle.hpp"
#include "question_capture.hpp"
#include "wake_features.hpp"

#include <atomic>
#include <cstdint>
#include <optional>
#include <span>

namespace stackchan::standalone {

class WakeVoiceEntry final {
 public:
  WakeVoiceEntry(Session& session, const WakeProfile& enrolled,
                 PersistentGuard& ledger, VoiceApiPort& api,
                 VoiceSpeakerPort& speaker, const std::atomic_bool& stop,
                 const std::atomic_bool& owner_consent,
                 const std::atomic_bool& trusted_time,
                 const std::atomic_bool& speaker_busy)
      : session_(session), enrolled_(enrolled), ledger_(ledger), api_(api),
        speaker_(speaker), stop_(stop), consent_(owner_consent),
        time_(trusted_time), speaker_busy_(speaker_busy) {}

  std::optional<uint64_t> detect(std::span<const int16_t> wake_pcm24k,
                                 uint64_t now_ms) {
    if (stop_.load() || speaker_busy_.load() || !consent_.load() ||
        session_.state() != State::wake_wait) return std::nullopt;
    const auto feature = wake_mfcc_from_24k(wake_pcm24k);
    if (!feature || !enrolled_.accepts(*feature)) return std::nullopt;
    return session_.wake(now_ms);
  }

  bool question_started(uint64_t now_ms, uint64_t epoch) {
    if (stop_.load() || speaker_busy_.load() || !consent_.load()) return false;
    return session_.speech_started(now_ms, epoch);
  }

  bool answer(std::span<const int16_t> question_pcm24k, uint64_t now_ms,
              uint64_t unix_seconds, const VoiceModelConfig& models) {
    if (stop_.load() || speaker_busy_.load() || !consent_.load()) return false;
    OfflineVoiceCycle cycle(session_, ledger_, api_, speaker_, stop_, consent_, time_);
    return cycle.run(question_pcm24k, now_ms, unix_seconds, models);
  }

  // Exact session epoch + completed capture are mandatory before dispatch.
  // Consume/zero the PCM even on failure; never resend a stale utterance.
  bool answer_captured(QuestionCapture& capture, uint64_t epoch,
                       uint64_t now_ms, uint64_t unix_seconds,
                       const VoiceModelConfig& models) {
    if (capture.status() != CaptureResult::ready) return false;
    if (session_.state() != State::record || session_.epoch() != epoch ||
        stop_.load() || speaker_busy_.load() || !consent_.load()) {
      capture.reset();
      return false;
    }
    const bool result = answer(capture.audio(), now_ms, unix_seconds, models);
    capture.reset();
    return result;
  }

 private:
  Session& session_;
  const WakeProfile& enrolled_;
  PersistentGuard& ledger_;
  VoiceApiPort& api_;
  VoiceSpeakerPort& speaker_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& time_;
  const std::atomic_bool& speaker_busy_;
};

}  // namespace stackchan::standalone

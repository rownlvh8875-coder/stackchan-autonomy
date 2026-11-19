// SPDX-License-Identifier: MIT
// Single-threaded, compile-only voice-turn coordination. Does not start hardware.
#pragma once

#include "audio_guard.hpp"
#include "mic_frame_bridge.hpp"
#include "wake_voice_entry.hpp"

#include <atomic>
#include <cstdint>

namespace stackchan::standalone {

enum class VoiceTurnStep { inactive, waiting_for_speech, recording, answered, aborted };

// Orchestrates an ALREADY-approved and initialized audio guard after a wake
// event. The device transport and real speech models are separate tasks.
// Caller must serialize arm/poll/cancel; STOP is an atomic external latch.
class VoiceTurnCoordinator final {
 public:
  VoiceTurnCoordinator(Session& session, PersistentGuard& ledger,
                       WakeVoiceEntry& entry, MicFrameBridge& bridge,
                       AudioGuard& audio, const std::atomic_bool& stop,
                       const std::atomic_bool& consent,
                       const std::atomic_bool& speaker_busy)
      : session_(session), ledger_(ledger), entry_(entry), bridge_(bridge),
        audio_(audio), stop_(stop), consent_(consent),
        speaker_busy_(speaker_busy) {}

  bool arm(uint64_t epoch, uint64_t now_ms) {
    if (active_ || faulted_ || stop_.load() || !consent_.load() ||
        speaker_busy_.load() || audio_.state() != AudioState::idle)
      return false;
    session_.tick(now_ms);
    if (session_.state() != State::ready || session_.epoch() != epoch)
      return false;
    if (!audio_.capture_begin()) {
      abort();
      return false;
    }
    active_ = true;
    epoch_ = epoch;
    speech_started_ = false;
    return true;
  }

  VoiceTurnStep poll(uint64_t now_ms, uint64_t unix_seconds,
                     const VoiceModelConfig& models) {
    if (faulted_) return VoiceTurnStep::aborted;
    if (!active_) return VoiceTurnStep::inactive;
    if (stop_.load() || !consent_.load() || speaker_busy_.load())
      return abort();
    session_.tick(now_ms);
    if (session_.epoch() != epoch_ ||
        (session_.state() != State::ready && session_.state() != State::record))
      return abort();

    const CaptureResult event = bridge_.capture(capture_);
    if (event == CaptureResult::rejected || stop_.load() ||
        !consent_.load() || speaker_busy_.load())
      return abort();

    if (event == CaptureResult::speech_started && !speech_started_) {
      if (!entry_.question_started(now_ms, epoch_)) return abort();
      speech_started_ = true;
    }
    if (event == CaptureResult::ready) {
      if (!speech_started_ || session_.state() != State::record ||
          !audio_.capture_end())
        return abort();
      active_ = false; // No more microphone reads while cloud stages run.
      const bool okay = entry_.answer_captured(capture_, epoch_, now_ms,
                                                unix_seconds, models);
      if (!okay) return abort();
      return VoiceTurnStep::answered;
    }
    return speech_started_ ? VoiceTurnStep::recording :
                             VoiceTurnStep::waiting_for_speech;
  }

  VoiceTurnStep cancel() { return abort(); }
  bool faulted() const { return faulted_; }
  bool active() const { return active_; }
  bool has_question_audio() const { return !capture_.audio().empty(); }

 private:
  VoiceTurnStep abort() {
    faulted_ = true; // Fail-closed: only new owner-authorized lifecycle may reset.
    active_ = false;
    speech_started_ = false;
    epoch_ = 0;
    capture_.reset();
    audio_.stop();
    ledger_.cancel_permit();
    session_.stop();
    return VoiceTurnStep::aborted;
  }

  Session& session_;
  PersistentGuard& ledger_;
  WakeVoiceEntry& entry_;
  MicFrameBridge& bridge_;
  AudioGuard& audio_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& speaker_busy_;
  QuestionCapture capture_;
  uint64_t epoch_ = 0;
  bool active_ = false;
  bool speech_started_ = false;
  bool faulted_ = false;
};

} // namespace stackchan::standalone

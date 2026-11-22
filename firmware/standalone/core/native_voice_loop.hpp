// SPDX-License-Identifier: MIT
// Dormant single-owner assembly of existing wake and question controllers.
// Local bootstrap supplies *live* readiness; no hardware/API setup or consent
// is manufactured here. app_main does not construct this class.
#pragma once
#include "native_wake_controller.hpp"
#include "voice_turn_coordinator.hpp"
#include <functional>
#include <utility>

namespace stackchan::standalone {
enum class NativeVoiceStep { listening, questioning, answered, cooldown, stopped };

class NativeVoiceLoop final {
 public:
  NativeVoiceLoop(Session& session, PersistentGuard& ledger,
                  NativeWakeController& wake, VoiceTurnCoordinator& turn,
                  AudioGuard& audio, NativeWakePort& model,
                  const std::atomic_bool& stop, const std::atomic_bool& consent,
                  const std::atomic_bool& speaker_busy,
                  std::function<bool()> live_readiness)
      : session_(session), ledger_(ledger), wake_(wake), turn_(turn),
        audio_(audio), model_(model), stop_(stop), consent_(consent),
        busy_(speaker_busy), readiness_(std::move(live_readiness)) {}
  NativeVoiceLoop(const NativeVoiceLoop&) = delete;
  NativeVoiceLoop& operator=(const NativeVoiceLoop&) = delete;
  ~NativeVoiceLoop() { if (started_) (void)cancel(); }

  // Serialize on the audio owner task. The caller supplies monotonic time,
  // paces wake polls within the existing 100ms bound and handles physical STOP
  // independently of this synchronous task (including during TLS/playback).
  NativeVoiceStep poll(uint64_t now_ms, uint64_t unix_seconds,
                       const VoiceModelConfig& models) {
    if (faulted_) return NativeVoiceStep::stopped;
    if (!live_ready()) return cancel();
    started_ = true;
    session_.tick(now_ms);
    if (turn_.active()) {
      if (wake_.active()) return cancel();
      const auto result = turn_.poll(now_ms, unix_seconds, models,
                                     [this] { return live_ready(); });
      if (result == VoiceTurnStep::answered) return NativeVoiceStep::answered;
      if (result == VoiceTurnStep::no_speech) return NativeVoiceStep::cooldown;
      if (result == VoiceTurnStep::aborted || result == VoiceTurnStep::inactive)
        return cancel();
      return NativeVoiceStep::questioning;
    }
    if (session_.state() == State::cooldown) return NativeVoiceStep::cooldown;
    if (session_.state() != State::wake_wait) return cancel();
    if (!wake_.active() && (!wake_.begin(now_ms) || !live_ready())) return cancel();
    const auto event = wake_.poll(now_ms);
    if (!live_ready()) return cancel();
    if (event.step == NativeWakeStep::detected) {
      if (!event.epoch ||
          !turn_.arm(*event.epoch, now_ms, QuestionCapture::Start::after_quiet) ||
          !live_ready())
        return cancel();
      return NativeVoiceStep::questioning;
    }
    if (event.step != NativeWakeStep::listening) return cancel();
    return NativeVoiceStep::listening;
  }

  NativeVoiceStep cancel() {
    if (faulted_) return NativeVoiceStep::stopped;
    faulted_ = true; // No implicit resume, retry, or re-use of a pending epoch.
    (void)wake_.cancel();
    (void)turn_.cancel();
    ledger_.cancel_permit();
    audio_.stop();
    session_.stop();
    return NativeVoiceStep::stopped;
  }

 private:
  bool live_ready() const {
    return !stop_.load() && consent_.load() && readiness_ && readiness_() &&
           !stop_.load() && consent_.load() && model_.ready() && !busy_.load();
  }

  Session& session_; PersistentGuard& ledger_; NativeWakeController& wake_;
  VoiceTurnCoordinator& turn_; AudioGuard& audio_; NativeWakePort& model_;
  const std::atomic_bool& stop_; const std::atomic_bool& consent_;
  const std::atomic_bool& busy_;
  std::function<bool()> readiness_;
  bool started_ = false, faulted_ = false;
};
} // namespace stackchan::standalone

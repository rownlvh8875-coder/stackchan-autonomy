// SPDX-License-Identifier: MIT
// Shared guarded dialog after a trusted local detector. No device/API startup.
#pragma once
#include "offline_voice_cycle.hpp"
#include "question_capture.hpp"
#include <atomic>
#include <cstdint>
#include <functional>
#include <optional>
#include <span>
namespace stackchan::standalone {
class VoiceDialogEntry {
 public:
  VoiceDialogEntry(Session& session,PersistentGuard& ledger,VoiceApiPort& api,
                   VoiceSpeakerPort& speaker,const std::atomic_bool& stop,
                   const std::atomic_bool& consent,const std::atomic_bool& trusted_time,
                   const std::atomic_bool& speaker_busy)
      : session_(session),ledger_(ledger),api_(api),speaker_(speaker),stop_(stop),
        consent_(consent),time_(trusted_time),speaker_busy_(speaker_busy) {}
  virtual ~VoiceDialogEntry()=default;
  bool wake_allowed() const {
    return !stop_.load() && !speaker_busy_.load() && consent_.load() &&
           session_.state()==State::wake_wait;
  }
  // Local detector event only; no SCFG/cloud handler invokes this operation.
  std::optional<uint64_t> confirmed_wake(uint64_t now_ms) {
    if (!wake_allowed()) return std::nullopt;
    ledger_.cancel_permit();
    return session_.wake(now_ms);
  }
  std::optional<uint64_t> confirmed_builtin_wake(uint64_t now_ms,bool model_ready) {
    if (!wake_allowed() || !model_ready) return std::nullopt;
    auto epoch=session_.wake(now_ms);
    if (!epoch || !ledger_.admit_builtin_wake(*epoch,consent_.load(),model_ready)) {
      ledger_.cancel_permit();session_.stop();return std::nullopt;
    }
    return epoch;
  }
  void cancel_pending_wake() { ledger_.cancel_permit(); }
  bool question_started(uint64_t now_ms,uint64_t epoch) {
    if(stop_.load() || speaker_busy_.load() || !consent_.load())return false;
    return session_.speech_started(now_ms,epoch);
  }
  bool answer(std::span<const int16_t> pcm,uint64_t now_ms,uint64_t unix_seconds,
              const VoiceModelConfig& models,
              const std::function<bool()>& live_readiness = {}) {
    if(stop_.load() || speaker_busy_.load() || !consent_.load())return false;
    OfflineVoiceCycle cycle(session_,ledger_,api_,speaker_,stop_,consent_,time_,
                            live_readiness);
    return cycle.run(pcm,now_ms,unix_seconds,models);
  }
  bool answer_captured(QuestionCapture& capture,uint64_t epoch,uint64_t now_ms,
                       uint64_t unix_seconds,const VoiceModelConfig& models,
                       const std::function<bool()>& live_readiness = {}) {
    if(capture.status()!=CaptureResult::ready)return false;
    if(session_.state()!=State::record || session_.epoch()!=epoch ||
       stop_.load() || speaker_busy_.load() || !consent_.load()) {
      capture.reset();return false;
    }
    const bool result=answer(capture.audio(),now_ms,unix_seconds,models,live_readiness);
    capture.reset();return result;
  }
 private:
  Session& session_;PersistentGuard& ledger_;VoiceApiPort& api_;VoiceSpeakerPort& speaker_;
  const std::atomic_bool& stop_;const std::atomic_bool& consent_;
  const std::atomic_bool& time_;const std::atomic_bool& speaker_busy_;
};
} // namespace stackchan::standalone

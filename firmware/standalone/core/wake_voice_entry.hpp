// SPDX-License-Identifier: MIT
// Legacy enrolled MFCC/DTW detector, sharing guarded dialog with native models.
#pragma once
#include "voice_dialog_entry.hpp"
#include "wake_features.hpp"
namespace stackchan::standalone {
class WakeVoiceEntry final : public VoiceDialogEntry {
 public:
  WakeVoiceEntry(Session& session,const WakeProfile& enrolled,PersistentGuard& ledger,
                 VoiceApiPort& api,VoiceSpeakerPort& speaker,const std::atomic_bool& stop,
                 const std::atomic_bool& owner_consent,const std::atomic_bool& trusted_time,
                 const std::atomic_bool& speaker_busy)
      : VoiceDialogEntry(session,ledger,api,speaker,stop,owner_consent,trusted_time,speaker_busy),
        enrolled_(enrolled) {}
  std::optional<uint64_t> detect(std::span<const int16_t> wake_pcm24k,uint64_t now_ms) {
    if(!wake_allowed())return std::nullopt;
    const auto feature=wake_mfcc_from_24k(wake_pcm24k);
    if(!feature || !enrolled_.accepts(*feature))return std::nullopt;
    return confirmed_wake(now_ms);
  }
 private:
  const WakeProfile& enrolled_;
};
} // namespace stackchan::standalone

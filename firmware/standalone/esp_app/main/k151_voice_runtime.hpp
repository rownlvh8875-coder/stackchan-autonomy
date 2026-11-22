// SPDX-License-Identifier: MIT
#pragma once

#include "guarded_voice_speaker.hpp"
#include "k151_mic_reader.hpp"
#include "k151_pcm_speaker_sink.hpp"
#include "k151_voice_api_adapter.hpp"
#include "k151_wakenet_port.hpp"
#include "native_voice_loop.hpp"

namespace stackchan::standalone {

// One owner task operates a prepared codec and its AudioGuard and takes over
// the already provisioned Wi-Fi/time port. The physical STOP producer is
// independent. The borrowed ports and flags outlive this object.
class K151VoiceRuntime final {
 public:
  K151VoiceRuntime(PersistentGuard& ledger, K151CodecPort& codec, AudioGuard& audio,
                   K151WifiTimePort& network, const std::atomic_bool& local_owner,
                   const std::atomic_bool& paid_consent, const std::atomic_bool& stop);
  K151VoiceRuntime(const K151VoiceRuntime&) = delete;
  K151VoiceRuntime& operator=(const K151VoiceRuntime&) = delete;
  ~K151VoiceRuntime();

  // The board owner calls this only after independent local paid consent.
  // Supply the model pack embedded in this app's read-only flash. On success
  // use poll() before the next 10ms frame and keep polling through cooldown.
  // Start takes network ownership once the prerequisites pass.
  bool start(VoiceModelConfig models, std::span<const uint8_t> model_pack);
  NativeVoiceStep poll();
  void stop();
  static const char* compiled_link_marker();

 private:
  bool admission_ready() const;
  bool live_ready() const;

  PersistentGuard& ledger_;
  K151CodecPort& codec_;
  AudioGuard& audio_;
  K151WifiTimePort& network_;
  const std::atomic_bool& owner_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& stop_;
  std::atomic_bool busy_{false};
  Session session_;
  K151WakeNetPort model_;
  K151MicReader mic_;
  K151PcmSpeakerSink sink_;
  GuardedVoiceSpeaker speaker_;
  K151VoiceApiAdapter api_;
  VoiceDialogEntry dialog_;
  MicFrameBridge bridge_;
  VoiceTurnCoordinator turn_;
  NativeWakeController wake_;
  NativeVoiceLoop loop_;
  VoiceModelConfig models_;
  bool attempted_ = false;
  bool active_ = false;
};

} // namespace stackchan::standalone

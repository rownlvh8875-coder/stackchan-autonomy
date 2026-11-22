// SPDX-License-Identifier: MIT
#pragma once

#include "guarded_voice_speaker.hpp"
#include "k151_mic_reader.hpp"
#include "k151_pcm_speaker_sink.hpp"
#include "k151_voice_api_adapter.hpp"
#include "k151_wakenet_port.hpp"
#include "native_voice_loop.hpp"

namespace stackchan::standalone {

// One owner task takes over a locally provisioned Wi-Fi/time port and owns
// the codec and AudioGuard. The physical STOP producer is independent.
// The ledger, network, flags and existing I2C1 board bus outlive this object.
// Only the board owner task may access devices on that bus.
class K151VoiceRuntime final {
 public:
  K151VoiceRuntime(PersistentGuard& ledger, K151WifiTimePort& network,
                   const std::atomic_bool& local_owner, const std::atomic_bool& paid_consent,
                   const std::atomic_bool& budget_writes, const std::atomic_bool& stop,
                   K151AudioBoardEvidence evidence, i2c_master_bus_handle_t board_bus);
  K151VoiceRuntime(const K151VoiceRuntime&) = delete;
  K151VoiceRuntime& operator=(const K151VoiceRuntime&) = delete;
  ~K151VoiceRuntime();

  // The board owner calls this only after independent local paid consent.
  // Supply the model pack in read-only app flash, with static storage duration.
  // Start adopts the active network on success. Poll pumps association/time
  // before opening audio and must continue through listening and cooldown.
  // A rejected start leaves the network with its original owner.
  bool start(VoiceModelConfig models, std::span<const uint8_t> model_pack);
  NativeVoiceStep poll();
  void stop();
  bool board_release_verified() const {
    return (phase_ == Phase::cold || phase_ == Phase::stopped) && !codec_.cleanup_unverified();
  }
  static const char* compiled_link_marker();

 private:
  enum class Phase { cold, waiting_network, operating, stopped };
  bool authorized() const;
  bool admission_ready() const;
  bool live_ready() const;
  bool start_voice();

  PersistentGuard& ledger_;
  K151WifiTimePort& network_;
  const std::atomic_bool& owner_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& budget_writes_;
  const std::atomic_bool& stop_;
  const K151AudioBoardEvidence evidence_;
  const i2c_master_bus_handle_t board_bus_;
  K151CodecPort codec_;
  AudioGuard audio_;
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
  std::span<const uint8_t> model_pack_;
  Phase phase_ = Phase::cold;
};

} // namespace stackchan::standalone

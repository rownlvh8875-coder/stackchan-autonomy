// SPDX-License-Identifier: MIT
#pragma once

#include "k151_owner_setup.hpp"
#include "k151_voice_runtime.hpp"
#include "nvs_port.hpp"

namespace stackchan::standalone {

// Call only from the device-local owner task. Setup and the authorization
// flags and the registered I2C1 bus outlive this object. The owner task
// serializes all access to the bus. The HOLD entrypoint links a marker only.
class K151VoiceBootstrap final {
 public:
  K151VoiceBootstrap(K151LocalOwnerSetup& setup, const std::atomic_bool& paid_consent,
                     const std::atomic_bool& budget_writes, K151AudioBoardEvidence evidence,
                     i2c_master_bus_handle_t board_bus);
  K151VoiceBootstrap(const K151VoiceBootstrap&) = delete;
  K151VoiceBootstrap& operator=(const K151VoiceBootstrap&) = delete;

  // A separate local action may initialize an absent budget. Without it,
  // startup requires an existing valid ledger. No USB frame grants either
  // budget permission. The model pack is the static read-only app asset.
  bool start(VoiceModelConfig models, std::span<const uint8_t> model_pack,
             bool allow_first_budget);
  NativeVoiceStep poll();
  void stop();
  static const char* compiled_link_marker();

 private:
  bool authorized() const;
  bool confirmed_setup();

  K151LocalOwnerSetup& setup_;
  const std::atomic_bool& paid_consent_;
  const std::atomic_bool& budget_writes_;
  const K151AudioBoardEvidence evidence_;
  const i2c_master_bus_handle_t board_bus_;
  IsolatedNvs storage_;
  PersistentGuard ledger_{storage_};
  K151WifiTimePort network_;
  K151VoiceRuntime voice_;
  bool attempted_ = false;
};

} // namespace stackchan::standalone

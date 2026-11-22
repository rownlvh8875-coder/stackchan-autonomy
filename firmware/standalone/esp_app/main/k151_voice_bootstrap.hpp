// SPDX-License-Identifier: MIT
#pragma once

#include "k151_owner_setup.hpp"
#include "k151_voice_runtime.hpp"
#include "nvs_port.hpp"
#include <optional>

namespace stackchan::standalone {

class K151LcdPanel;
class K151SetupLvgl;
struct K151VoiceHandoff;
enum class K151VoiceMode { continuous, one_paid_turn };

// Call only from the device-local owner task. Setup and the authorization
// flags, the panel and the registered I2C1 bus outlive this object. The owner task
// serializes all access to the bus. The HOLD entrypoint links a marker only.
class K151VoiceBootstrap final {
 public:
  explicit K151VoiceBootstrap(const K151VoiceHandoff& handoff, K151AudioBoardEvidence evidence);
  K151VoiceBootstrap(K151LocalOwnerSetup& setup, K151LcdPanel& panel,
                     const std::atomic_bool& paid_consent,
                     const std::atomic_bool& budget_writes, K151AudioBoardEvidence evidence,
                     i2c_master_bus_handle_t board_bus,
                     K151VoiceMode mode = K151VoiceMode::continuous,
                     K151SetupLvgl* view = nullptr);
  ~K151VoiceBootstrap();
  K151VoiceBootstrap(const K151VoiceBootstrap&) = delete;
  K151VoiceBootstrap& operator=(const K151VoiceBootstrap&) = delete;

  // A separate local action may initialize an absent budget. Without it,
  // startup requires an existing valid ledger. No USB frame grants either
  // budget permission. The model pack is the static read-only app asset.
  // Setup and panel use K151DisplayStop::flag(). Finish local touch input
  // before start. The IRQ monitor owns the line after the panel's final acknowledgment.
  bool start(VoiceModelConfig models, std::span<const uint8_t> model_pack,
             bool allow_first_budget);
  bool start(VoiceModelConfig models, std::span<const uint8_t> model_pack);
  NativeVoiceStep poll();
  void stop();
  bool board_release_verified() const {
    return !display_stop_owned_ && voice_.board_release_verified();
  }
  static const char* compiled_link_marker();

 private:
  bool authorized() const;
  bool confirmed_setup();

  K151LocalOwnerSetup& setup_;
  K151LcdPanel& panel_;
  const std::atomic_bool& paid_consent_;
  const std::atomic_bool& budget_writes_;
  const K151AudioBoardEvidence evidence_;
  const i2c_master_bus_handle_t board_bus_;
  K151SetupLvgl* const view_;
  IsolatedNvs storage_;
  PersistentGuard ledger_;
  K151WifiTimePort network_;
  K151VoiceRuntime voice_;
  bool attempted_ = false;
  bool display_stop_owned_ = false;
  std::optional<bool> reviewed_first_budget_;
};

} // namespace stackchan::standalone

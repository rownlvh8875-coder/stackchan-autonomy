// SPDX-License-Identifier: MIT
#include "k151_voice_bootstrap.hpp"
#include "k151_install_hold.hpp"
#include <esp_timer.h>
#include <utility>

namespace stackchan::standalone {

K151VoiceBootstrap::K151VoiceBootstrap(K151LocalOwnerSetup& setup,
    const std::atomic_bool& paid_consent, const std::atomic_bool& budget_writes,
    K151AudioBoardEvidence evidence, i2c_master_bus_handle_t board_bus)
    : setup_(setup), paid_consent_(paid_consent), budget_writes_(budget_writes),
      evidence_(evidence), board_bus_(board_bus),
      storage_(setup.owner_, paid_consent, budget_writes, setup.stop_),
      voice_(ledger_, network_, setup.owner_, paid_consent, budget_writes, setup.stop_,
             evidence_, board_bus_) {}

bool K151VoiceBootstrap::authorized() const {
  return setup_.owner_.load() && paid_consent_.load() && budget_writes_.load() &&
         !setup_.stop_.load();
}

bool K151VoiceBootstrap::confirmed_setup() {
  const auto now_us = esp_timer_get_time();
  return now_us >= 0 && setup_.poll(static_cast<uint64_t>(now_us / 1000)) && setup_.ready();
}

bool K151VoiceBootstrap::start(VoiceModelConfig models, std::span<const uint8_t> pack,
                               bool allow_first_budget) {
  if (attempted_ || !K151InstallHold::device_activation_allowed() ||
      !K151CodecPort::playback_enabled_by_build() || !evidence_.verified() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) || !models.valid() || pack.empty() ||
      !authorized() || !confirmed_setup())
    return false;
  attempted_ = true;
  if (!storage_.init_without_erase() || !authorized() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) ||
      !ledger_.restore_budget_for_setup(allow_first_budget) || !authorized() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) || !confirmed_setup()) {
    setup_.stop();
    return false;
  }
  if (!setup_.start_wifi_once(network_)) {
    setup_.stop();
    return false;
  }
  if (authorized() && voice_.start(std::move(models), pack)) return true;
  (void)network_.shutdown(); // Voice has not adopted the Wi-Fi port.
  return false;
}

NativeVoiceStep K151VoiceBootstrap::poll() {
  if (!attempted_) return NativeVoiceStep::stopped;
  if (authorized()) return voice_.poll();
  stop();
  return NativeVoiceStep::stopped;
}

void K151VoiceBootstrap::stop() {
  attempted_ = true;
  setup_.stop();
  voice_.stop();
}

const char* K151VoiceBootstrap::compiled_link_marker() {
  auto volatile start = &K151VoiceBootstrap::start;
  auto volatile poll = &K151VoiceBootstrap::poll;
  (void)start;
  (void)poll;
  return "K151 owner setup and durable budget handoff linked; NOT STARTED";
}

} // namespace stackchan::standalone

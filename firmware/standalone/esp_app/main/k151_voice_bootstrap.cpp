// SPDX-License-Identifier: MIT
#include "k151_voice_bootstrap.hpp"
#include "k151_install_hold.hpp"
#include "k151_display_stop.hpp"
#include "k151_setup_lvgl.hpp"
#include "k151_voice_handoff.hpp"
#ifdef STACKCHAN_K151_CONVERSATION_IMAGE
#include "k151_conversation_policy.hpp"
#endif
#include <esp_log.h>
#include <esp_timer.h>
#include <utility>

namespace stackchan::standalone {

K151VoiceBootstrap::K151VoiceBootstrap(const K151VoiceHandoff& handoff,
                                       K151AudioBoardEvidence evidence)
    : K151VoiceBootstrap(handoff.setup, handoff.panel, handoff.paid_consent,
                         handoff.budget_writes, evidence, handoff.bus,
                         handoff.one_paid_turn ? K151VoiceMode::one_paid_turn
                                               : K151VoiceMode::continuous, &handoff.view) {
  reviewed_first_budget_ = handoff.allow_first_budget;
}

K151VoiceBootstrap::K151VoiceBootstrap(K151LocalOwnerSetup& setup, K151LcdPanel& panel,
    const std::atomic_bool& paid_consent, const std::atomic_bool& budget_writes,
    K151AudioBoardEvidence evidence, i2c_master_bus_handle_t board_bus, K151VoiceMode mode,
    K151SetupLvgl* view)
    : setup_(setup), panel_(panel), paid_consent_(paid_consent), budget_writes_(budget_writes),
      evidence_(evidence), board_bus_(board_bus), view_(view),
      storage_(setup.owner_, paid_consent, budget_writes, setup.stop_),
      ledger_(storage_, mode == K151VoiceMode::one_paid_turn),
      voice_(ledger_, network_, setup.owner_, paid_consent, budget_writes, setup.stop_,
             evidence_, board_bus_,
             [this](K151VoiceStatus status) { return !view_ || view_->present_voice_status(status); }) {}

K151VoiceBootstrap::~K151VoiceBootstrap() {
  if (display_stop_owned_) stop();
}

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
      (allow_first_budget && !reviewed_first_budget_.value_or(true)) ||
      !K151CodecPort::playback_enabled_by_build() || !evidence_.verified() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) || !models.valid() || pack.empty() ||
      &setup_.stop_ != &K151DisplayStop::flag() || !authorized() || !confirmed_setup())
    return false;
  attempted_ = true;
  const auto display_stop = K151DisplayStop::arm(board_bus_, panel_);
  display_stop_owned_ = display_stop != K151DisplayStop::ArmResult::unavailable;
  if (display_stop != K151DisplayStop::ArmResult::armed) {
    stop();
    return false;
  }
  PersistentGuard::BudgetBaselineCheck baseline;
#ifdef STACKCHAN_K151_CONVERSATION_IMAGE
  if (k151_local_conversation_policy().mode == K151ConversationBuildMode::one_paid_turn)
    baseline = k151_local_trial_budget_matches;
#endif
  if ((view_ && !view_->present_voice_status(K151VoiceStatus::connecting)) ||
      !confirmed_setup() || !authorized() || !storage_.init_without_erase() || !authorized() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) ||
      !ledger_.restore_budget_for_setup(allow_first_budget, baseline) || !authorized() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) || !confirmed_setup()) {
    stop();
    return false;
  }
  if (!setup_.start_wifi_once(network_)) {
    stop();
    return false;
  }
  if (authorized() && voice_.start(std::move(models), pack)) return true;
  (void)network_.shutdown(); // Voice has not adopted the Wi-Fi port.
  stop();
  return false;
}

bool K151VoiceBootstrap::start(VoiceModelConfig models, std::span<const uint8_t> pack) {
  return start(std::move(models), pack, reviewed_first_budget_.value_or(false));
}

NativeVoiceStep K151VoiceBootstrap::poll() {
  if (!display_stop_owned_) return NativeVoiceStep::stopped;
  if (authorized()) {
    const auto result = voice_.poll();
    if (result == NativeVoiceStep::trial_standby) {
      stop();
      return board_release_verified() ? result : NativeVoiceStep::stopped;
    }
    if (result != NativeVoiceStep::stopped) return result;
  }
  stop();
  return NativeVoiceStep::stopped;
}

void K151VoiceBootstrap::stop() {
  attempted_ = true;
  setup_.stop();
  voice_.stop();
  if (display_stop_owned_) {
    if (K151DisplayStop::disarm()) display_stop_owned_ = false;
    else ESP_LOGE("k151_bootstrap", "display STOP cleanup incomplete");
  }
}

const char* K151VoiceBootstrap::compiled_link_marker() {
  using Start = bool (K151VoiceBootstrap::*)(VoiceModelConfig, std::span<const uint8_t>);
  auto volatile start = static_cast<Start>(&K151VoiceBootstrap::start);
  auto volatile poll = &K151VoiceBootstrap::poll;
  (void)start;
  (void)poll;
  return "K151 owner setup and durable budget handoff linked; NOT STARTED";
}

} // namespace stackchan::standalone

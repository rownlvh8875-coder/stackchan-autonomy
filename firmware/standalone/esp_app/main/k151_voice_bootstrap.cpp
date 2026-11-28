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
namespace {
constexpr auto kCheckpointKey = IsolatedNvs::kTrialCheckpointKey;
constexpr size_t kCheckpointMax = RebootTrialScope{}.id.size() + 818;
}

K151VoiceBootstrap::K151VoiceBootstrap(
    const K151VoiceHandoff& handoff, K151AudioBoardEvidence evidence,
    std::optional<RebootTrialScope> reboot_trial,
    PersistentGuard::BudgetBaselineCheck first_trial_budget)
    : K151VoiceBootstrap(handoff.setup, handoff.panel, handoff.paid_consent,
                         handoff.budget_writes, evidence, handoff.bus,
                         handoff.one_paid_turn ? K151VoiceMode::one_paid_turn
                                               : K151VoiceMode::continuous, &handoff.view,
                         reboot_trial) {
  reviewed_first_budget_ = handoff.allow_first_budget;
  save_after_setup_ = handoff.save_after_setup;
  first_trial_budget_ = std::move(first_trial_budget);
}

K151VoiceBootstrap::K151VoiceBootstrap(K151LocalOwnerSetup& setup, K151LcdPanel& panel,
    const std::atomic_bool& paid_consent, const std::atomic_bool& budget_writes,
    K151AudioBoardEvidence evidence, i2c_master_bus_handle_t board_bus, K151VoiceMode mode,
    K151SetupLvgl* view, std::optional<RebootTrialScope> reboot_trial)
    : setup_(setup), panel_(panel), paid_consent_(paid_consent), budget_writes_(budget_writes),
      evidence_(evidence), board_bus_(board_bus), view_(view),
      one_paid_turn_(mode == K151VoiceMode::one_paid_turn),
      reboot_trial_(reboot_trial),
      storage_(setup.owner_, paid_consent, budget_writes, setup.stop_, reboot_trial_.has_value()),
      ledger_(storage_, one_paid_turn_, reboot_trial_),
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

std::vector<uint8_t> K151VoiceBootstrap::checkpoint_record(std::span<const uint8_t> budget) const {
  const auto& id = reboot_trial_->id;
  std::vector<uint8_t> record(id.begin(), id.end());
  record.insert(record.end(), budget.begin(), budget.end());
  return record;
}

bool K151VoiceBootstrap::checkpoint_matches(const ReadValue& previous) {
  if (!authorized() || previous.code != ReadCode::found) return false;
  const auto expected = checkpoint_record(previous.bytes);
  const auto checkpoint = storage_.read(kCheckpointKey, kCheckpointMax);
  return checkpoint.code == ReadCode::found && checkpoint.bytes == expected && authorized();
}

bool K151VoiceBootstrap::save_checkpoint(std::span<const uint8_t> budget) {
  const auto existing = storage_.read(kCheckpointKey, kCheckpointMax);
  if (!authorized() || existing.code != ReadCode::missing || !existing.bytes.empty()) return false;
  const auto record = checkpoint_record(budget);
  if (!storage_.commit(kCheckpointKey, record) || !authorized()) return false;
  const auto saved = storage_.read(kCheckpointKey, kCheckpointMax);
  return saved.code == ReadCode::found && saved.bytes == record && authorized();
}

bool K151VoiceBootstrap::start(VoiceModelConfig models, std::span<const uint8_t> pack,
                               bool allow_first_budget) {
  const bool after_reboot = reboot_trial_ && reboot_trial_->boot == RebootTrialBoot::after_reboot;
  if (attempted_ || !K151InstallHold::device_activation_allowed() ||
      (reboot_trial_ && (!view_ || one_paid_turn_ ||
       (after_reboot ? allow_first_budget || save_after_setup_
                     : !save_after_setup_ || !first_trial_budget_))) ||
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
  if (reboot_trial_) {
    baseline = [this, after_reboot](const ReadValue& previous) {
      if (after_reboot) return checkpoint_matches(previous);
      const auto checkpoint = storage_.read(kCheckpointKey, kCheckpointMax);
      return checkpoint.code == ReadCode::missing && checkpoint.bytes.empty() &&
             first_trial_budget_(previous);
    };
  }
  const auto getting_ready = after_reboot ? K151VoiceStatus::checking_budget
                                          : K151VoiceStatus::connecting;
  if ((view_ && !view_->present_voice_status(getting_ready)) ||
      !confirmed_setup() || !authorized() || !storage_.init_without_erase() || !authorized() ||
      !K151CodecPort::is_registered_board_bus(board_bus_) ||
      !ledger_.restore_budget_for_setup(allow_first_budget, baseline) || !authorized() ||
      (after_reboot && !view_->present_voice_status(K151VoiceStatus::budget_verified)) ||
      !K151CodecPort::is_registered_board_bus(board_bus_) || !confirmed_setup()) {
    stop();
    return false;
  }
  // Publish the saved setup only after the paid review and durable budget.
  // A reboot after the save always expects an existing budget.
  if (save_after_setup_ && (!setup_.save_first(*save_after_setup_, authorized()) || !authorized() ||
                            !K151CodecPort::is_registered_board_bus(board_bus_))) {
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
      // Close the voice ports before displaying success. The display STOP
      // monitor stays armed for the final frame.
      if (reboot_trial_ && reboot_trial_->boot == RebootTrialBoot::before_reboot) {
        const bool completed = voice_.finish_trial() && authorized() &&
            K151CodecPort::is_registered_board_bus(board_bus_) &&
            save_reboot_checkpoint_and_present();
        stop();
        return completed && board_release_verified() ? NativeVoiceStep::reboot_ready
                                                     : NativeVoiceStep::stopped;
      }
      voice_.stop();
      const bool completed = voice_.board_release_verified() && authorized() &&
                             (!view_ || view_->present_voice_status(K151VoiceStatus::trial_finished)) &&
                             authorized();
      stop();
      return completed && board_release_verified() ? result : NativeVoiceStep::stopped;
    }
    if (result != NativeVoiceStep::stopped) return result;
    // Only an internal trial failure can keep the last rendered frame. A
    // physical STOP or revoked consent takes the immediate shutdown path.
    show_failed_trial_ = one_paid_turn_ && view_ && authorized();
  }
  stop();
  return NativeVoiceStep::stopped;
}

void K151VoiceBootstrap::stop() {
  attempted_ = true;
  ledger_.stop();
  setup_.stop();
  voice_.stop();
  if (display_stop_owned_) {
    if (K151DisplayStop::disarm()) display_stop_owned_ = false;
    else ESP_LOGE("k151_bootstrap", "display STOP cleanup incomplete");
  }
}

bool K151VoiceBootstrap::save_reboot_checkpoint_and_present() {
  // Keep STOP armed through the frame and both verified writes. A failed
  // frame can never publish the resume marker.
  return ledger_.prepare_trial_reboot(authorized(), [this](auto budget) {
    return save_checkpoint(budget) && view_->present_voice_status(K151VoiceStatus::reboot_ready) &&
           authorized();
  });
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

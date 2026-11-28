// SPDX-License-Identifier: MIT
#pragma once

#include "k151_owner_session.hpp"
#include "k151_voice_bootstrap.hpp"

namespace stackchan::standalone {

struct K151RebootTrialPlan {
  std::array<uint8_t, 32> id{};
  PersistentGuard::BudgetBaselineCheck first_budget;
};

// Static lifetime preserves the owner of the board bus if child teardown is
// ambiguous. Use one pinned task, including for STOP cleanup. Poll within the
// existing setup and wake sampling limits.
class K151ConversationOwner final {
 public:
  enum class Phase {
    idle, setup, cloud_off, voice_review, voice, showing_trial_result, trial_complete, stopped, fault
  };
  struct Progress {
    Phase phase;
    NativeVoiceStep voice = NativeVoiceStep::stopped;
  };

  static K151ConversationOwner& instance();
  K151ConversationOwner(const K151ConversationOwner&) = delete;
  K151ConversationOwner& operator=(const K151ConversationOwner&) = delete;

  bool start(K151AudioBoardEvidence evidence, bool physical_lcd_verified,
             SavedOwnerCredentials* saved = nullptr, OwnerUnlockPort* unlock = nullptr);
  // The caller supplies the reviewed deployment scope and a static app-flash
  // asset. The robot's separate local review must also pass.
  bool request_voice(VoiceModelConfig models, std::span<const uint8_t> model_pack,
                     bool paid_scope_approved, bool budget_scope_approved,
                     bool allow_first_budget, K151VoiceMode mode,
                     std::optional<K151RebootTrialPlan> reboot_trial = std::nullopt);
  Progress poll();
  bool shutdown();
  std::optional<scpswire::SetupFailure> early_setup_failure() const {
    return setup_.early_setup_failure();
  }
  static const char* compiled_link_marker();

 private:
  K151ConversationOwner() = default;
  ~K151ConversationOwner() = default;
  bool on_owner_task() const;
  Progress finish(Phase phase, NativeVoiceStep result = NativeVoiceStep::stopped);
  Progress finish_trial_result(NativeVoiceStep result);

  K151OwnerSession setup_;
  std::optional<K151VoiceBootstrap> voice_;
  K151AudioBoardEvidence evidence_{};
  VoiceModelConfig models_;
  std::span<const uint8_t> pack_;
  std::optional<RebootTrialScope> trial_scope_;
  PersistentGuard::BudgetBaselineCheck first_trial_budget_;
  TaskHandle_t task_ = nullptr;
  int core_ = -1;
  Progress progress_{Phase::idle};
  int64_t trial_result_at_us_ = 0;
  bool released_ = false;
};

} // namespace stackchan::standalone

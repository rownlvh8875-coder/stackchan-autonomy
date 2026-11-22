// SPDX-License-Identifier: MIT
#include "k151_conversation_owner.hpp"

#include <esp_timer.h>
#include <utility>

namespace stackchan::standalone {

K151ConversationOwner& K151ConversationOwner::instance() {
  static K151ConversationOwner owner;
  return owner;
}

bool K151ConversationOwner::on_owner_task() const {
  return task_ && task_ == xTaskGetCurrentTaskHandle() && core_ == xPortGetCoreID();
}

bool K151ConversationOwner::start(K151AudioBoardEvidence evidence, bool physical_lcd_verified) {
  if (task_ || !evidence.verified() || !physical_lcd_verified) return false;
  task_ = xTaskGetCurrentTaskHandle();
  if (!task_) return false;
  core_ = xPortGetCoreID();
  evidence_ = evidence;
  if (!setup_.start(evidence.exact_board_verified, physical_lcd_verified)) {
    finish(Phase::fault);
    return false;
  }
  progress_ = {Phase::setup};
  return true;
}

bool K151ConversationOwner::request_voice(VoiceModelConfig models,
    std::span<const uint8_t> model_pack, bool paid_scope_approved, bool budget_scope_approved,
    bool allow_first_budget, K151VoiceMode mode) {
  if (!on_owner_task() || progress_.phase != Phase::cloud_off ||
      !models.valid() || model_pack.empty() ||
      !setup_.request_voice_review(paid_scope_approved, budget_scope_approved, allow_first_budget,
                                   mode == K151VoiceMode::one_paid_turn)) return false;
  models_ = std::move(models);
  pack_ = model_pack;
  progress_ = {Phase::voice_review};
  return true;
}

K151ConversationOwner::Progress K151ConversationOwner::poll() {
  if (!task_) return {Phase::idle};
  if (!on_owner_task()) return {Phase::fault};
  if (progress_.phase == Phase::showing_trial_result) {
    const auto now_us = esp_timer_get_time();
    if (now_us < trial_result_at_us_ || now_us - trial_result_at_us_ >= 3'000'000)
      return finish_trial_result(progress_.voice);
    return progress_;
  }
  if (progress_.phase == Phase::voice) {
    const auto result = voice_->poll();
    if (result == NativeVoiceStep::trial_standby || voice_->keep_failed_trial_frame()) {
      // Bootstrap has already closed audio, model, network and the STOP monitor.
      // Keep the last frame visible briefly. The owner task polls the dwell.
      voice_.reset();
      (void)setup_.poll(); // Clear the remaining local approvals on the STOP latch.
      trial_result_at_us_ = esp_timer_get_time();
      if (trial_result_at_us_ < 0) return finish_trial_result(result);
      return progress_ = {Phase::showing_trial_result, result};
    }
    if (result == NativeVoiceStep::stopped) return finish(Phase::stopped);
    return progress_ = {Phase::voice, result};
  }
  if (progress_.phase == Phase::setup || progress_.phase == Phase::cloud_off ||
      progress_.phase == Phase::voice_review) {
    const auto step = setup_.poll();
    if (step == K151OwnerSession::Step::fault) return finish(Phase::fault);
    if (step == K151OwnerSession::Step::stopped) return finish(Phase::stopped);
    if (step == K151OwnerSession::Step::ready) return progress_ = {Phase::cloud_off};
    if (step == K151OwnerSession::Step::voice_ready) {
      const auto handoff = setup_.handoff();
      if (!handoff) return finish(Phase::fault);
      voice_.emplace(*handoff, evidence_);
      if (!voice_->start(std::move(models_), std::exchange(pack_, {}))) return finish(Phase::fault);
      return progress_ = {Phase::voice, NativeVoiceStep::waiting_network};
    }
  }
  return progress_;
}

K151ConversationOwner::Progress K151ConversationOwner::finish(Phase phase, NativeVoiceStep result) {
  return progress_ = shutdown() ? Progress{phase, result} : Progress{Phase::fault};
}

K151ConversationOwner::Progress K151ConversationOwner::finish_trial_result(NativeVoiceStep result) {
  return finish(result == NativeVoiceStep::trial_standby ? Phase::trial_complete : Phase::stopped,
                result);
}

bool K151ConversationOwner::shutdown() {
  if (!task_) return true;
  if (!on_owner_task()) return false;
  if (released_) return true;
  models_ = {};
  pack_ = {};
  if (voice_) {
    voice_->stop();
    if (!voice_->board_release_verified()) {
      (void)setup_.poll(); // Revoke local authorization on the latched STOP.
      progress_ = {Phase::fault};
      return false;
    }
    voice_.reset();
  }
  released_ = setup_.shutdown();
  progress_ = {released_ ? Phase::stopped : Phase::fault};
  return released_;
}

const char* K151ConversationOwner::compiled_link_marker() {
  auto volatile instance = &K151ConversationOwner::instance;
  auto volatile start = &K151ConversationOwner::start;
  auto volatile request = &K151ConversationOwner::request_voice;
  auto volatile poll = &K151ConversationOwner::poll;
  (void)instance;
  (void)start;
  (void)request;
  (void)poll;
  return "K151 setup, consent and native conversation linked; NOT STARTED";
}

} // namespace stackchan::standalone

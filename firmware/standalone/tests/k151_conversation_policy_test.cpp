// SPDX-License-Identifier: MIT
#include "k151_conversation_policy.hpp"
#include <cassert>

using namespace stackchan::standalone;

int main() {
  K151ConversationPolicy policy;
  K151ConversationBootFacts facts;
  facts.factory_identity_sha256[0] = 0x23; // Synthetic, never a device identifier.
  facts.slot_offset = 0x510000;
  facts.slot_bytes = 0x4f0000;
  facts.flash_bytes = 16 * 1024 * 1024;
  facts.nvs_offset = 0x9000;
  facts.nvs_bytes = 0x4000;
  facts.chip_revision = 2;
  facts.esp32s3 = facts.ota1 = facts.psram_ready = facts.security_matches = true;
  using Boot = K151ConversationBootStage;
  assert(conversation_boot_stage(policy, facts) == Boot::policy);
  assert(!admit_conversation_boot(policy, facts));

  policy.expected_factory_identity = facts.factory_identity_sha256;
  policy.output = {true, true, true, true, true, true, true};
  policy.physical_lcd_verified = policy.exclusive_i2s0_verified = true;
  policy.mode = K151ConversationBuildMode::one_paid_turn;
  assert(!admit_conversation_boot(policy, facts));
  policy.paid_scope_approved = true;
  assert(!admit_conversation_boot(policy, facts));
  policy.budget_scope_approved = true;
  assert(!admit_conversation_boot(policy, facts)); // One paid turn needs a durable baseline.
  policy.trial_budget_sha256 = facts.factory_identity_sha256; // Synthetic fixture.
  const auto trial = admit_conversation_boot(policy, facts);
  assert(trial && trial->audio.verified() && trial->mode == K151ConversationBuildMode::one_paid_turn);
  assert(conversation_boot_stage(policy, facts) == Boot::ready);
  {
    auto rejected = facts;
    rejected.esp32s3 = false;
    assert(conversation_boot_stage(policy, rejected) == Boot::chip);
    rejected = facts;
    rejected.factory_identity_sha256 = {};
    assert(conversation_boot_stage(policy, rejected) == Boot::identity);
    rejected = facts;
    rejected.slot_offset = 0;
    assert(conversation_boot_stage(policy, rejected) == Boot::slot);
    rejected = facts;
    rejected.psram_ready = false;
    assert(conversation_boot_stage(policy, rejected) == Boot::psram);
    rejected = facts;
    rejected.security_matches = false;
    assert(conversation_boot_stage(policy, rejected) == Boot::security);
    rejected = facts;
    rejected.flash_bytes = 0;
    assert(conversation_boot_stage(policy, rejected) == Boot::flash);
    rejected = facts;
    rejected.nvs_bytes = 0;
    assert(conversation_boot_stage(policy, rejected) == Boot::nvs);
  }
  assert(!trial->allow_first_budget && !trial->owner_hmac_slot);
  auto trial_with_slot = policy;
  trial_with_slot.owner_hmac_slot = 2;
  assert(conversation_boot_stage(trial_with_slot, facts) == Boot::policy);
  assert(matches_reviewed_trial_budget(policy, false, facts.factory_identity_sha256));
  assert(!matches_reviewed_trial_budget(policy, false, K151BudgetDigest{}));
  assert(!matches_reviewed_trial_budget(policy, false, std::nullopt));
  assert(!matches_reviewed_trial_budget(policy, true, std::nullopt));
  auto observed_trial = policy;
  observed_trial.output = {true, true, false, false, false, false, true};
  assert(!admit_conversation_boot(observed_trial, facts));
  const K151OneTurnDeviceEvidence observations{{1}, {2}, {3}};
  observed_trial.one_turn_device_evidence = observations;
  const auto observed = admit_conversation_boot(observed_trial, facts);
  assert(observed && observed->mode == K151ConversationBuildMode::one_paid_turn);
  assert(matches_reviewed_trial_budget(observed_trial, false, facts.factory_identity_sha256));
  assert(!matches_reviewed_trial_budget(observed_trial, false, K151BudgetDigest{99}));
  for (auto field : {&K151OneTurnDeviceEvidence::normal_playback,
                     &K151OneTurnDeviceEvidence::usb_stop,
                     &K151OneTurnDeviceEvidence::panel_stop}) {
    auto denied = observed_trial;
    denied.one_turn_device_evidence.value().*field = {};
    assert(!admit_conversation_boot(denied, facts));
  }
  auto duplicate = observed_trial;
  duplicate.one_turn_device_evidence->panel_stop = observations.usb_stop;
  assert(!admit_conversation_boot(duplicate, facts));
  for (auto field : {&K151OutputEvidence::exact_board_revision_verified,
                     &K151OutputEvidence::exclusive_i2c_ownership_verified,
                     &K151OutputEvidence::dma_tx_empty_and_codec_idle_observable}) {
    auto denied = observed_trial;
    denied.output.*field = false;
    assert(!admit_conversation_boot(denied, facts));
  }
  for (auto field : {&K151ConversationPolicy::physical_lcd_verified,
                     &K151ConversationPolicy::exclusive_i2s0_verified,
                     &K151ConversationPolicy::paid_scope_approved,
                     &K151ConversationPolicy::budget_scope_approved}) {
    auto denied = observed_trial;
    denied.*field = false;
    assert(!admit_conversation_boot(denied, facts));
  }
  auto wrong_board = facts;
  wrong_board.factory_identity_sha256[0] = 0x42;
  assert(!admit_conversation_boot(observed_trial, wrong_board));
  auto continuous_from_trial = observed_trial;
  continuous_from_trial.mode = K151ConversationBuildMode::continuous;
  continuous_from_trial.trial_budget_sha256.reset();
  assert(!admit_conversation_boot(continuous_from_trial, facts));
  continuous_from_trial.output = policy.output;
  assert(!admit_conversation_boot(continuous_from_trial, facts));

  policy.trial_budget_sha256.reset();
  policy.trial_budget_must_be_missing = true;
  assert(!admit_conversation_boot(policy, facts)); // First write needs its own scope.
  policy.allow_first_budget = true;
  const auto led = admit_conversation_boot(policy, facts);
  assert(led && led->allow_first_budget);
  assert(matches_reviewed_trial_budget(policy, true, std::nullopt));
  assert(!matches_reviewed_trial_budget(policy, false, facts.factory_identity_sha256));
  policy.trial_budget_sha256 = facts.factory_identity_sha256;
  assert(!admit_conversation_boot(policy, facts)); // Ambiguous baseline.
  policy.trial_budget_sha256.reset();
  policy.trial_budget_must_be_missing = false;
  policy.mode = K151ConversationBuildMode::continuous;
  assert(conversation_boot_stage(policy, facts) == Boot::policy);
  policy.owner_hmac_slot = 6;
  assert(conversation_boot_stage(policy, facts) == Boot::policy);
  policy.owner_hmac_slot = 2;
  assert(conversation_boot_stage(policy, facts) == Boot::security);
  facts.security_matches = false;
  facts.protected_owner_hmac_slot = 3;
  assert(conversation_boot_stage(policy, facts) == Boot::security);
  facts.protected_owner_hmac_slot = 2;
  const auto continuous = admit_conversation_boot(policy, facts);
  assert(continuous && continuous->mode == K151ConversationBuildMode::continuous &&
         continuous->owner_hmac_slot == 2);

  for (bool K151ConversationPolicy::*field : {
       &K151ConversationPolicy::physical_lcd_verified, &K151ConversationPolicy::exclusive_i2s0_verified,
       &K151ConversationPolicy::paid_scope_approved, &K151ConversationPolicy::budget_scope_approved}) {
    auto denied = policy;
    denied.*field = false;
    assert(!admit_conversation_boot(denied, facts));
  }
  for (bool K151OutputEvidence::*field : {
       &K151OutputEvidence::exact_board_revision_verified, &K151OutputEvidence::exclusive_i2c_ownership_verified,
       &K151OutputEvidence::axp2101_rails_measured, &K151OutputEvidence::aw9523_reset_sequence_verified,
       &K151OutputEvidence::aw88298_hardware_mute_measured, &K151OutputEvidence::independent_stop_latency_measured,
       &K151OutputEvidence::dma_tx_empty_and_codec_idle_observable}) {
    auto denied = policy;
    denied.output.*field = false;
    assert(!admit_conversation_boot(denied, facts));
  }
  for (bool K151ConversationBootFacts::*field : {
       &K151ConversationBootFacts::esp32s3, &K151ConversationBootFacts::ota1,
       &K151ConversationBootFacts::psram_ready}) {
    auto denied = facts;
    denied.*field = false;
    assert(!admit_conversation_boot(policy, denied));
  }
  auto missing_key = facts;
  missing_key.protected_owner_hmac_slot.reset();
  assert(!admit_conversation_boot(policy, missing_key));
  auto reversible = policy;
  reversible.owner_hmac_slot.reset();
  reversible.reversible_owner_unlock = true;
  facts.security_matches = true;
  assert(conversation_boot_stage(reversible, facts) == Boot::security);
  facts.reversible_unlock_verified = true;
  auto local = admit_conversation_boot(reversible, facts);
  assert(local && local->reversible_owner_unlock && !local->owner_hmac_slot);
  auto incomplete_output = reversible;
  incomplete_output.output.independent_stop_latency_measured = false;
  assert(conversation_boot_stage(incomplete_output, facts) == Boot::policy);
  auto observed_instead = reversible;
  observed_instead.one_turn_device_evidence = observations;
  assert(conversation_boot_stage(observed_instead, facts) == Boot::policy);
  auto combined = reversible;
  combined.mode = K151ConversationBuildMode::reboot_trial;
  assert(!admit_conversation_boot(combined, facts));
  combined.reboot_trial_id = K151BudgetDigest{0x37};
  combined.trial_budget_must_be_missing = true;
  const auto trial_plan = admit_conversation_boot(combined, facts);
  assert(trial_plan && trial_plan->reboot_trial_id == combined.reboot_trial_id &&
         trial_plan->reversible_owner_unlock && !trial_plan->owner_hmac_slot);
  assert(matches_reviewed_trial_budget(combined, true, std::nullopt));
  assert(!matches_reviewed_trial_budget(combined, false, K151BudgetDigest{1}));
  auto missing_measurement = combined;
  missing_measurement.output.aw88298_hardware_mute_measured = false;
  assert(!admit_conversation_boot(missing_measurement, facts));
  missing_measurement.one_turn_device_evidence = observations;
  assert(!admit_conversation_boot(missing_measurement, facts));
  combined.reboot_trial_id.reset();
  assert(!admit_conversation_boot(combined, facts));
  reversible.owner_hmac_slot = 2;
  assert(conversation_boot_stage(reversible, facts) == Boot::policy);
  facts.security_matches = false;
  for (std::uint32_t K151ConversationBootFacts::*field : {
       &K151ConversationBootFacts::slot_offset, &K151ConversationBootFacts::slot_bytes,
       &K151ConversationBootFacts::flash_bytes, &K151ConversationBootFacts::nvs_offset,
       &K151ConversationBootFacts::nvs_bytes}) {
    auto denied = facts;
    ++(denied.*field);
    assert(!admit_conversation_boot(policy, denied));
  }
  auto other_board = facts;
  other_board.factory_identity_sha256[3] = 1;
  assert(!admit_conversation_boot(policy, other_board));
  other_board = facts;
  other_board.chip_revision = 3;
  assert(!admit_conversation_boot(policy, other_board));
  policy.expected_factory_identity = {};
  other_board.factory_identity_sha256 = {};
  assert(!admit_conversation_boot(policy, other_board));
}

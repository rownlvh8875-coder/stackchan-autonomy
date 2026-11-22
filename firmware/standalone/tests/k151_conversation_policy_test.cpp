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
  assert(!trial->allow_first_budget);
  assert(matches_reviewed_trial_budget(policy, false, facts.factory_identity_sha256));
  assert(!matches_reviewed_trial_budget(policy, false, K151BudgetDigest{}));
  assert(!matches_reviewed_trial_budget(policy, false, std::nullopt));
  assert(!matches_reviewed_trial_budget(policy, true, std::nullopt));
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
  const auto continuous = admit_conversation_boot(policy, facts);
  assert(continuous && continuous->mode == K151ConversationBuildMode::continuous);

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
       &K151ConversationBootFacts::psram_ready, &K151ConversationBootFacts::security_matches}) {
    auto denied = facts;
    denied.*field = false;
    assert(!admit_conversation_boot(policy, denied));
  }
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

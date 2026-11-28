// SPDX-License-Identifier: MIT
#pragma once

#include "board_evidence.hpp"
#include "k151_mic_only_evidence.hpp"
#include "k151_output_evidence.hpp"
#include <algorithm>
#include <array>
#include <optional>

namespace stackchan::standalone {

enum class K151ConversationBuildMode { hold, one_paid_turn, continuous, reboot_trial };
enum class K151ConversationBootStage : unsigned {
  policy = 0, chip = 1, identity = 2, slot = 3, psram = 4,
  security = 5, flash = 6, nvs = 7, ready = 8
};
using K151BudgetDigest = std::array<std::uint8_t, 32>;

struct K151OneTurnDeviceEvidence {
  // SHA256 of the three separately reviewed reports from the same board.
  std::array<std::uint8_t, 32> normal_playback{};
  std::array<std::uint8_t, 32> usb_stop{};
  std::array<std::uint8_t, 32> panel_stop{};

  constexpr bool complete() const {
    const auto present = [](const auto& digest) {
      return std::ranges::any_of(digest, [](auto value) { return value != 0; });
    };
    return present(normal_playback) && present(usb_stop) && present(panel_stop) &&
           normal_playback != usb_stop && normal_playback != panel_stop && usb_stop != panel_stop;
  }
};

// A private deployment record supplies reviewed evidence and scoped approval.
// Installation authorization is checked separately against the finished image.
struct K151ConversationPolicy {
  std::array<std::uint8_t, 32> expected_factory_identity{};
  K151OutputEvidence output{};
  bool physical_lcd_verified = false;
  bool exclusive_i2s0_verified = false;
  bool paid_scope_approved = false;
  bool budget_scope_approved = false;
  bool allow_first_budget = false;
  K151ConversationBuildMode mode = K151ConversationBuildMode::hold;
  // Bind the first boot of a paid trial to a private snapshot of sc_gpt/budget.
  // Missing is a separate, explicitly reviewed first-provisioning case.
  std::optional<K151BudgetDigest> trial_budget_sha256 = std::nullopt;
  bool trial_budget_must_be_missing = false;
  std::optional<K151OneTurnDeviceEvidence> one_turn_device_evidence = std::nullopt;
  // Number of the reviewed dedicated HMAC_UP eFuse key, never the key bytes.
  std::optional<std::uint8_t> owner_hmac_slot = std::nullopt;
  bool reversible_owner_unlock = false;
  std::optional<K151BudgetDigest> reboot_trial_id = std::nullopt;
};

// Read-only, observed on each approved boot. Empty fields fail closed.
struct K151ConversationBootFacts {
  std::array<std::uint8_t, 32> factory_identity_sha256{};
  std::uint32_t slot_offset = 0;
  std::uint32_t slot_bytes = 0;
  std::uint32_t flash_bytes = 0;
  std::uint32_t nvs_offset = 0;
  std::uint32_t nvs_bytes = 0;
  std::uint16_t chip_revision = 0;
  bool esp32s3 = false;
  bool ota1 = false;
  bool psram_ready = false;
  bool security_matches = false;
  std::optional<std::uint8_t> protected_owner_hmac_slot = std::nullopt;
  bool reversible_unlock_verified = false;
};

struct K151AdmittedConversation {
  K151AudioBoardEvidence audio;
  bool physical_lcd_verified;
  bool paid_scope_approved;
  bool budget_scope_approved;
  bool allow_first_budget;
  K151ConversationBuildMode mode;
  std::optional<std::uint8_t> owner_hmac_slot;
  bool reversible_owner_unlock;
  std::optional<K151BudgetDigest> reboot_trial_id;
};

inline constexpr bool local_conversation_scope_complete(const K151ConversationPolicy& policy) {
  const bool first_budget = policy.trial_budget_must_be_missing &&
                            policy.allow_first_budget && !policy.trial_budget_sha256;
  const bool existing_budget = !policy.trial_budget_must_be_missing && policy.trial_budget_sha256 &&
      std::ranges::any_of(*policy.trial_budget_sha256, [](auto value) { return value != 0; });
  bool scoped = false;
  switch (policy.mode) {
    case K151ConversationBuildMode::one_paid_turn:
      scoped = !policy.owner_hmac_slot && !policy.reversible_owner_unlock &&
               !policy.reboot_trial_id && (first_budget || existing_budget);
      break;
    case K151ConversationBuildMode::continuous:
      scoped = !policy.reboot_trial_id && !policy.trial_budget_must_be_missing &&
               !policy.trial_budget_sha256 &&
               (policy.reversible_owner_unlock ? !policy.owner_hmac_slot
                                               : policy.owner_hmac_slot && *policy.owner_hmac_slot < 6);
      break;
    case K151ConversationBuildMode::reboot_trial:
      scoped = policy.reversible_owner_unlock && !policy.owner_hmac_slot &&
               (first_budget || existing_budget) && policy.reboot_trial_id &&
               std::ranges::any_of(*policy.reboot_trial_id, [](auto byte) { return byte != 0; });
      break;
    case K151ConversationBuildMode::hold:
      return false;
  }
  // Device observations are a separate output basis for a single paid turn.
  // The final HOLD verdict on the other path means its measured-output checks passed.
  const bool output_reviewed = policy.one_turn_device_evidence
      ? policy.mode == K151ConversationBuildMode::one_paid_turn &&
        policy.one_turn_device_evidence->complete() && policy.output.exact_board_revision_verified &&
        policy.output.exclusive_i2c_ownership_verified &&
        policy.output.dma_tx_empty_and_codec_idle_observable
      : assess_k151_output(policy.output) == OutputBlock::hold_image_never_enables_audio;
  return scoped && output_reviewed && policy.physical_lcd_verified && policy.exclusive_i2s0_verified &&
         policy.paid_scope_approved && policy.budget_scope_approved &&
         std::ranges::any_of(policy.expected_factory_identity, [](auto value) { return value != 0; });
}

inline K151ConversationBootStage conversation_boot_stage(
    const K151ConversationPolicy& policy, const K151ConversationBootFacts& boot) {
  using Stage = K151ConversationBootStage;
  if (!local_conversation_scope_complete(policy)) return Stage::policy;
  if (!boot.esp32s3 || boot.chip_revision != 2) return Stage::chip;
  if (policy.expected_factory_identity != boot.factory_identity_sha256) return Stage::identity;
  if (!boot.ota1 || !k151::board_probe_location_allowed(boot.slot_offset, boot.slot_bytes,
                                                       boot.esp32s3, boot.chip_revision))
    return Stage::slot;
  if (!boot.psram_ready) return Stage::psram;
  if (boot.nvs_offset != 0x9000 || boot.nvs_bytes != 0x4000) return Stage::nvs;
  const bool security_ok = policy.mode == K151ConversationBuildMode::one_paid_turn
      ? boot.security_matches
      : policy.reversible_owner_unlock ? boot.security_matches && boot.reversible_unlock_verified
                                       : boot.protected_owner_hmac_slot == policy.owner_hmac_slot;
  if (!security_ok) return Stage::security;
  if (boot.flash_bytes != 16 * 1024 * 1024) return Stage::flash;
  return Stage::ready;
}

inline std::optional<K151AdmittedConversation> admit_conversation_boot(
    const K151ConversationPolicy& policy, const K151ConversationBootFacts& boot) {
  if (conversation_boot_stage(policy, boot) != K151ConversationBootStage::ready)
    return std::nullopt;
  return K151AdmittedConversation{
      {policy.output.exact_board_revision_verified, policy.exclusive_i2s0_verified},
      policy.physical_lcd_verified, policy.paid_scope_approved, policy.budget_scope_approved,
      policy.allow_first_budget, policy.mode, policy.owner_hmac_slot, policy.reversible_owner_unlock,
      policy.reboot_trial_id};
}

inline bool matches_reviewed_trial_budget(const K151ConversationPolicy& policy, bool missing,
                                           const std::optional<K151BudgetDigest>& observed) {
  if ((policy.mode != K151ConversationBuildMode::one_paid_turn &&
       policy.mode != K151ConversationBuildMode::reboot_trial) ||
      !local_conversation_scope_complete(policy))
    return false;
  return policy.trial_budget_must_be_missing ? missing && !observed
      : !missing && observed && policy.trial_budget_sha256 == observed;
}

// These symbols exist only in the separate conversation project configuration.
struct ReadValue;
const K151ConversationPolicy& k151_local_conversation_policy();
#ifdef STACKCHAN_K151_PRIVATE_POLICY
const char* k151_local_release_marker();
#endif
bool k151_local_trial_budget_matches(const ReadValue& read);
bool k151_conversation_boot_armed();

} // namespace stackchan::standalone

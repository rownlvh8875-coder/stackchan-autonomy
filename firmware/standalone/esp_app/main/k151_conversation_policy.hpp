// SPDX-License-Identifier: MIT
#pragma once

#include "board_evidence.hpp"
#include "k151_mic_only_evidence.hpp"
#include "k151_output_evidence.hpp"
#include <algorithm>
#include <optional>

namespace stackchan::standalone {

enum class K151ConversationBuildMode { hold, one_paid_turn, continuous };

// A private deployment record supplies measurements and scoped approval.
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
};

struct K151AdmittedConversation {
  K151AudioBoardEvidence audio;
  bool physical_lcd_verified;
  bool paid_scope_approved;
  bool budget_scope_approved;
  bool allow_first_budget;
  K151ConversationBuildMode mode;
};

inline bool local_conversation_scope_complete(const K151ConversationPolicy& policy) {
  const bool scoped = policy.mode == K151ConversationBuildMode::one_paid_turn ||
                      policy.mode == K151ConversationBuildMode::continuous;
  // This final HOLD verdict means the preceding measured-output checks passed.
  const bool measured =
      assess_k151_output(policy.output) == OutputBlock::hold_image_never_enables_audio;
  return scoped && measured && policy.physical_lcd_verified && policy.exclusive_i2s0_verified &&
         policy.paid_scope_approved && policy.budget_scope_approved &&
         std::ranges::any_of(policy.expected_factory_identity, [](auto value) { return value != 0; });
}

inline std::optional<K151AdmittedConversation> admit_conversation_boot(
    const K151ConversationPolicy& policy, const K151ConversationBootFacts& boot) {
  if (!local_conversation_scope_complete(policy) ||
      policy.expected_factory_identity != boot.factory_identity_sha256 ||
      !boot.ota1 || !boot.psram_ready || !boot.security_matches ||
      !k151::board_probe_location_allowed(boot.slot_offset, boot.slot_bytes,
                                         boot.esp32s3, boot.chip_revision) ||
      boot.flash_bytes != 16 * 1024 * 1024 || boot.nvs_offset != 0x9000 ||
      boot.nvs_bytes != 0x4000)
    return std::nullopt;
  return K151AdmittedConversation{
      {policy.output.exact_board_revision_verified, policy.exclusive_i2s0_verified},
      policy.physical_lcd_verified, policy.paid_scope_approved, policy.budget_scope_approved,
      policy.allow_first_budget, policy.mode};
}

// These symbols exist only in the separate conversation project configuration.
const K151ConversationPolicy& k151_local_conversation_policy();
bool k151_conversation_boot_armed();

} // namespace stackchan::standalone

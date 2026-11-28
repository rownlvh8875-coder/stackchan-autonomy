// SPDX-License-Identifier: MIT
#include "k151_conversation_policy.hpp"
#include "persistent_store.hpp"
#include <psa/crypto.h>

namespace stackchan::standalone {
namespace {
#ifdef STACKCHAN_K151_PRIVATE_POLICY
constexpr K151ConversationPolicy policy =
#include "k151_private_policy.inc"
    ;
static_assert(local_conversation_scope_complete(policy), "Incomplete private K151 operating evidence");
#else
const K151ConversationPolicy policy{};
#endif
}

const K151ConversationPolicy& k151_local_conversation_policy() { return policy; }

#ifdef STACKCHAN_K151_PRIVATE_POLICY
const char* k151_local_release_marker() {
  if constexpr (policy.one_turn_device_evidence.has_value())
    return "K151_CONVERSATION_LOCAL_RELEASE_ONE_PAID_TURN_DEVICE_OBSERVED";
  else if constexpr (policy.mode == K151ConversationBuildMode::one_paid_turn)
    return "K151_CONVERSATION_LOCAL_RELEASE_ONE_PAID_TURN";
  else if constexpr (policy.mode == K151ConversationBuildMode::reboot_trial)
    return "K151_CONVERSATION_LOCAL_RELEASE_REBOOT_TRIAL";
  else if constexpr (policy.reversible_owner_unlock)
    return "K151_CONVERSATION_LOCAL_RELEASE_CONTINUOUS_LOCAL_UNLOCK";
  else
    return "K151_CONVERSATION_LOCAL_RELEASE_CONTINUOUS";
}
#endif

bool k151_local_trial_budget_matches(const ReadValue& read) {
  if (read.code == ReadCode::missing && read.bytes.empty())
    return matches_reviewed_trial_budget(policy, true, std::nullopt);
  if (read.code != ReadCode::found || read.bytes.empty()) return false;
  K151BudgetDigest digest{};
  std::size_t written = 0;
  if (psa_crypto_init() != PSA_SUCCESS ||
      psa_hash_compute(PSA_ALG_SHA_256, read.bytes.data(), read.bytes.size(), digest.data(),
                       digest.size(), &written) != PSA_SUCCESS || written != digest.size())
    return false;
  return matches_reviewed_trial_budget(policy, false, digest);
}

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
#include "k151_conversation_policy.hpp"
#include "persistent_store.hpp"
#include <psa/crypto.h>

namespace stackchan::standalone {
namespace {
#ifdef STACKCHAN_K151_PRIVATE_POLICY
const K151ConversationPolicy policy =
#include "k151_private_policy.inc"
    ;
#else
const K151ConversationPolicy policy{};
#endif
}

const K151ConversationPolicy& k151_local_conversation_policy() { return policy; }

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

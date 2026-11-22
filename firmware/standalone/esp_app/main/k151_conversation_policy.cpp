// SPDX-License-Identifier: MIT
#include "k151_conversation_policy.hpp"

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

} // namespace stackchan::standalone

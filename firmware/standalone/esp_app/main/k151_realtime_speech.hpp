// SPDX-License-Identifier: MIT
#pragma once

#include "offline_voice_cycle.hpp"

namespace stackchan::standalone {

class K151RealtimeSpeechPort final {
 public:
  // One fixed-host connection and one text-only response.create. No client
  // is kept between turns. The caller owns the credential and stage permit.
  bool synthesize_once(const VoiceApiRequest& request, std::string_view key,
                       const std::function<bool()>& network_ready,
                       const std::atomic_bool& consent, const std::atomic_bool& stop,
                       const std::function<bool()>& spend_dispatch,
                       std::vector<uint8_t>& pcm24k, uint64_t& completed_ms) const;
};

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
// Gated I2C observer; never called from the HOLD application.
#pragma once

#include <atomic>
#include "board_evidence.hpp"

namespace stackchan::standalone {
class K151ReadOnlyProbe final {
 public:
  static const char* compiled_link_marker();
  // Requires an explicit operator-level approval in a future hardware build.
  // A physical STOP must be independently implemented; polling is not a hard
  // real-time stop guarantee. No caller exists in the current build.
  bool observe_once(bool explicitly_authorized, const std::atomic_bool& stop,
                    k151::ReadOnlyEvidence& out) const;
};
}  // namespace stackchan::standalone

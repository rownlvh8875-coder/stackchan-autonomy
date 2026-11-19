// SPDX-License-Identifier: MIT
// Only this marker is linked by HOLD app_main. Setup is never constructed.
#include "k151_owner_setup.hpp"

namespace stackchan::standalone {
const char* K151LocalOwnerSetup::compiled_link_marker() {
  return "K151 first-use RAM-only owner setup state machine linked; NOT STARTED";
}
}  // namespace stackchan::standalone

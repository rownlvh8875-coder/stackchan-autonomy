// SPDX-License-Identifier: MIT
// Only this marker is linked by HOLD app_main. Setup is never constructed.
#include "k151_owner_setup.hpp"

namespace stackchan::standalone {
const char* K151LocalOwnerSetup::compiled_link_marker() {
  return "K151 first-use RAM-only owner setup state machine linked; NOT STARTED";
}

bool K151LocalOwnerSetup::start_wifi_once(K151WifiTimePort& network) {
  if (network_handoff_attempted_ || !setup_.ready() ||
      !owner_.load() || !input_.load() || stop_.load()) return false;
  network_handoff_attempted_ = true;
  // Explicitly pass no persistent credential store or NVS approval.
  const bool accepted = network.start(owner_.load(), input_.load(),
       secrets_.ssid(), secrets_.passphrase(), secrets_.api_key(), stop_);
  // Never retain a second copy after handoff, including on driver errors.
  setup_.cancel();
  if (stop_.load() && accepted) (void)network.shutdown();
  return accepted && !stop_.load();
}
}  // namespace stackchan::standalone

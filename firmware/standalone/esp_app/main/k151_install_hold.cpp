// SPDX-License-Identifier: MIT
// Linked to prove the no-install policy survives ESP-IDF cross-compilation.
#include "k151_install_hold.hpp"
#include "hardware_hold.hpp"

namespace stackchan::standalone {
static_assert(!kHardwareActivationInHoldImage);
static_assert(!K151InstallHold::kDeviceActivationEnabled);
bool K151InstallHold::device_activation_allowed() { return kDeviceActivationEnabled; }
const char* K151InstallHold::compiled_link_marker() {
  return "K151 startup/recovery HOLD: no hardware activation or install target";
}
}  // namespace stackchan::standalone

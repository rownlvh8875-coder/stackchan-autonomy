// SPDX-License-Identifier: MIT
// Linked to prove the no-install policy survives ESP-IDF cross-compilation.
#include "k151_install_hold.hpp"
#include "hardware_hold.hpp"
#ifdef STACKCHAN_K151_CONVERSATION_IMAGE
#include "k151_conversation_policy.hpp"
#endif

namespace stackchan::standalone {
static_assert(!kHardwareActivationInHoldImage);
static_assert(!K151InstallHold::kDeviceActivationEnabled);
bool K151InstallHold::device_activation_allowed() {
#ifdef STACKCHAN_K151_CONVERSATION_IMAGE
  return k151_conversation_boot_armed();
#else
  return kDeviceActivationEnabled;
#endif
}
bool K151InstallHold::display_activation_allowed() {
#if defined(STACKCHAN_K151_PANEL_PROBE) || defined(STACKCHAN_K151_SPEAKER_STOP_PROBE)
  return true;
#else
  return device_activation_allowed();
#endif
}
const char* K151InstallHold::compiled_link_marker() {
  return "K151 startup/recovery HOLD: no hardware activation or install target";
}
}  // namespace stackchan::standalone

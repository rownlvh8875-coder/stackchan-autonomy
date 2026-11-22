// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>
#include <driver/i2c_master.h>

namespace stackchan::standalone {

class K151LcdPanel;
class K151VoiceBootstrap;

// One display STOP source per boot. Call arm/disarm from the board owner task.
// Before arming, finish local touch input and release any panel contact. The
// bound panel acknowledges the final UI release before handoff. While armed, only
// this STOP source owns the expander interrupt masks and no task reads the
// registers that acknowledge the display or expander interrupts.
class K151DisplayStop final {
 public:
  static const std::atomic_bool& flag();

 private:
  friend class K151VoiceBootstrap;
  enum class ArmResult { unavailable, armed, owned_unarmed };
  static ArmResult arm(i2c_master_bus_handle_t board_bus, K151LcdPanel& panel);
  static bool disarm();
};

} // namespace stackchan::standalone

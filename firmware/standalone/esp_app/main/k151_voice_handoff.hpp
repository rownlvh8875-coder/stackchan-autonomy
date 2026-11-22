// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>
#include <driver/i2c_master.h>

namespace stackchan::standalone {

class K151LcdPanel;
class K151LocalOwnerSetup;
class K151OwnerSession;

// Borrowed from the pinned owner task after local setup and voice approval.
// The owner session and its bus outlive all users of this handoff.
struct K151VoiceHandoff {
  K151LocalOwnerSetup& setup;
  K151LcdPanel& panel;
  const i2c_master_bus_handle_t bus;
  const std::atomic_bool& paid_consent;
  const std::atomic_bool& budget_writes;
  const bool allow_first_budget;

 private:
  friend class K151OwnerSession;
  K151VoiceHandoff(K151LocalOwnerSetup& settings, K151LcdPanel& display,
                   i2c_master_bus_handle_t board_bus, const std::atomic_bool& paid,
                   const std::atomic_bool& writes, bool first_budget)
      : setup(settings), panel(display), bus(board_bus), paid_consent(paid),
        budget_writes(writes), allow_first_budget(first_budget) {}
};

} // namespace stackchan::standalone

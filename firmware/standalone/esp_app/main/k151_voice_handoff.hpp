// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>
#include <driver/i2c_master.h>

namespace stackchan::standalone {

class K151LcdPanel;
class K151LocalOwnerSetup;
class K151OwnerSession;
class K151SetupLvgl;
class SavedOwnerCredentials;

// Borrowed from the pinned owner task after local setup and voice approval.
// The owner session and its bus outlive all users of this handoff.
struct K151VoiceHandoff {
  K151LocalOwnerSetup& setup;
  K151LcdPanel& panel;
  K151SetupLvgl& view;
  const i2c_master_bus_handle_t bus;
  const std::atomic_bool& paid_consent;
  const std::atomic_bool& budget_writes;
  const bool allow_first_budget;
  const bool one_paid_turn;
  SavedOwnerCredentials* const save_after_setup;

 private:
  friend class K151OwnerSession;
  K151VoiceHandoff(K151LocalOwnerSetup& settings, K151LcdPanel& display, K151SetupLvgl& screen,
                   i2c_master_bus_handle_t board_bus, const std::atomic_bool& paid,
                   const std::atomic_bool& writes, bool first_budget, bool one_turn,
                   SavedOwnerCredentials* saved)
      : setup(settings), panel(display), view(screen), bus(board_bus), paid_consent(paid),
        budget_writes(writes), allow_first_budget(first_budget), one_paid_turn(one_turn),
        save_after_setup(saved) {}
};

} // namespace stackchan::standalone

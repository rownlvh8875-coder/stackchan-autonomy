// SPDX-License-Identifier: MIT
#pragma once

namespace stackchan::standalone {

// Current physical observations from the caller's exclusive audio owner.
// Stored board readback and synthetic bench flags cannot supply these.
struct K151MicOnlyEvidence {
  bool exact_board_verified = false;
  bool microphone_supply_and_clock_pins_verified = false;
  bool amplifier_isolation_with_input_clocks_verified = false;
  bool exclusive_i2s0_owner_verified = false;

  bool verified() const {
    return exact_board_verified && microphone_supply_and_clock_pins_verified &&
           amplifier_isolation_with_input_clocks_verified && exclusive_i2s0_owner_verified;
  }
};

}  // namespace stackchan::standalone

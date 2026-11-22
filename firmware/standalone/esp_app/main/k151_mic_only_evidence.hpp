// SPDX-License-Identifier: MIT
#pragma once

namespace stackchan::standalone {

// Current board and I2S ownership evidence supplied by the local diagnostic.
// The codec checks the board's power configuration and holds amp reset itself.
struct K151MicOnlyEvidence {
  bool exact_board_verified = false;
  bool exclusive_i2s0_owner_verified = false;

  bool verified() const {
    return exact_board_verified && exclusive_i2s0_owner_verified;
  }
};

}  // namespace stackchan::standalone

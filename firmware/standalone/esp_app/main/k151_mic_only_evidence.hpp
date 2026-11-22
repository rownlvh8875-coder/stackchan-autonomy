// SPDX-License-Identifier: MIT
#pragma once

namespace stackchan::standalone {

// Fixed, content-free stages shared by the receive-only port and trial report.
enum class K151MicWakeStage {
  admission, baseline_memory, model_prepare, input_format, model_reset, resident_memory,
  i2c_bus, board_power, amplifier_reset, board_release, i2s_rx, codec_prepare,
  codec_open, capture_clock, capture_read, wake_input, codec_release, complete,
};

// Board identity and I2S ownership supplied by the local owner. The port
// separately checks current power and reset configuration before codec use.
struct K151AudioBoardEvidence {
  bool exact_board_verified = false;
  bool exclusive_i2s0_owner_verified = false;

  bool verified() const {
    return exact_board_verified && exclusive_i2s0_owner_verified;
  }
};
using K151MicOnlyEvidence = K151AudioBoardEvidence;

}  // namespace stackchan::standalone

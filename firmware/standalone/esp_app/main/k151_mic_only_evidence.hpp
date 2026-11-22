// SPDX-License-Identifier: MIT
#pragma once

namespace stackchan::standalone {

// Fixed, content-free stages shared by the receive-only port and trial report.
enum class K151MicWakeStage {
  admission, baseline_memory, model_prepare, input_format, model_reset, resident_memory,
  i2c_bus, board_power, amplifier_reset, board_release, i2s_rx, codec_prepare,
  codec_open, capture_clock, capture_read, wake_input, codec_release, complete,
};

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

// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>

namespace stackchan::standalone {

// First failed checkpoint, with no register values or audio in the report.
enum class K151SpeakerStartupStage : uint8_t {
  none, audio_guard, admission, codec_open, codec_ready, i2s_tx_state, volume,
  muted_admission, clock_origin, standby_readback, clock_enable, wait_clock,
  mute_readback, amplifier_enable, wait_switching, attenuation, pre_unmute_status,
  unmute, post_unmute_status,
};

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
// Explicitly dormant AudioGuard ↔ K151CodecPort hooks, never used by app_main.
// No verified AXP2101/AW9523 power sequence, capture flush or TX DMA drain.
#pragma once

#include "audio_guard.hpp"
#include "k151_codec_port.hpp"

namespace stackchan::standalone {

// Returning success from a missing physical operation would be unsafe.
// Even if a future caller creates these hooks, AudioGuard initialization
// and playback drain fail closed in the HOLD build.
inline AudioHooks k151_unapproved_audio_hooks(K151CodecPort& codec) {
  return AudioHooks{
      [&codec]() { return codec.microphone_off(); },
      [&codec]() { return codec.speaker_off(); },
      []() { return false; }, // No validated power/reset/init transaction.
      [&codec]() { return codec.microphone_on(); },
      []() { return false; }, // Mic FIFO flush not measured on hardware.
      [&codec]() { return codec.speaker_on_low_volume(); },
      [&codec]() { return codec.drain_output_before_mute(); },
  };
}

} // namespace stackchan::standalone

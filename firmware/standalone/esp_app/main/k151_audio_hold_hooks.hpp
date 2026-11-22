// SPDX-License-Identifier: MIT
// Explicitly dormant AudioGuard ↔ K151CodecPort hooks, never used by app_main.
// Output hardware and capture flush still require device verification.
#pragma once

#include "audio_guard.hpp"
#include "k151_codec_port.hpp"

namespace stackchan::standalone {

// Returning success from a missing physical operation would be unsafe.
// AudioGuard initialization fails closed in the HOLD build.
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

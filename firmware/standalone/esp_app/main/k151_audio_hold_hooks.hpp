// SPDX-License-Identifier: MIT
// Owner-task AudioGuard hooks. The HOLD app does not construct them.
#pragma once

#include "audio_guard.hpp"
#include "k151_codec_port.hpp"

namespace stackchan::standalone {

inline AudioHooks k151_audio_hooks(K151CodecPort& codec, const std::atomic_bool& owner,
                                  const std::atomic_bool& stop, const std::atomic_bool& consent,
                                  K151AudioBoardEvidence evidence,
                                  i2c_master_bus_handle_t borrowed_bus = nullptr) {
  return AudioHooks{
      [&codec]() { return codec.microphone_off(); },
      [&codec, &consent]() { return codec.speaker_off(&consent); },
      [&codec, &owner, &stop, evidence, borrowed_bus]() {
        return codec.prepare(owner, stop, evidence, borrowed_bus);
      },
      [&codec]() { return codec.start_fresh_capture(); },
      [&codec]() { return codec.capture_idle(); },
      [&codec, &consent]() { return codec.speaker_on_low_volume(consent); },
      [&codec]() { return codec.drain_output_before_mute(); },
  };
}

} // namespace stackchan::standalone

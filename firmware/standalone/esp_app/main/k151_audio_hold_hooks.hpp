// SPDX-License-Identifier: MIT
// Owner-task AudioGuard hooks. The HOLD app does not construct them.
#pragma once

#include "audio_guard.hpp"
#include "k151_codec_port.hpp"

namespace stackchan::standalone {

inline AudioHooks k151_audio_hooks(K151CodecPort& codec, const std::atomic_bool& owner,
                                  const std::atomic_bool& stop, const std::atomic_bool& consent,
                                  K151AudioBoardEvidence evidence) {
  return AudioHooks{
      [&codec]() { return codec.microphone_off(); },
      [&codec]() { return codec.speaker_off(); },
      [&codec, &owner, &stop, evidence]() { return codec.prepare(owner, stop, evidence); },
      [&codec]() { return codec.start_fresh_capture(); },
      [&codec]() { return codec.capture_idle(); },
      [&codec, &consent]() { return codec.speaker_on_low_volume(consent); },
      [&codec]() { return codec.drain_output_before_mute(); },
  };
}

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
// HOST-TEST-ONLY contract fixture for ordering the AudioGuard lifecycle.
// NOT part of the ESP32-S3 firmware or a real board-evidence implementation.
// No I2C register writes, GPIO accesses, or hardware startup in this file.
#pragma once

#include "audio_guard.hpp"

#include <atomic>

namespace stackchan::standalone {

// Must be implemented by an independently audited, owner-approved K151
// hardware driver. No concrete implementation is supplied here.
// A successful codec write, a time delay, or an unverified boolean does NOT
// establish that DMA was drained or that the amplifier is electrically quiet.
class PhysicalAudioEvidence {
 public:
  virtual ~PhysicalAudioEvidence() = default;
  virtual bool force_amplifier_mute() = 0;
  virtual bool exact_board_confirmed() = 0;
  virtual bool power_rails_confirmed() = 0;
  virtual bool amplifier_reset_confirmed() = 0;
  virtual bool discard_microphone_dma() = 0;
  virtual bool output_dma_drained_after_last_write() = 0;
};

// TEST-ONLY binder: compile and exercise with FakeCodec, never K151CodecPort.
// AudioGuard attempts mute-first, then verifies evidence before codec prepare;
// no real board authorization is implied by the test booleans.
// Synchronous hooks require serialized use; they do not supply STOP latency.
template <typename Codec>
AudioHooks bind_verified_audio_hooks(
    Codec& codec, PhysicalAudioEvidence& board,
    const std::atomic_bool& owner_approved,
    const std::atomic_bool& physical_stop) {

  return AudioHooks{
      // Mic off must work during an owner revocation or physical STOP.
      [&codec]() { return codec.microphone_off(); },
      // Hard mute is attempted first, independent codec close second, even
      // when either step fails. Neither failure can be treated as success.
      [&codec, &board]() {
        const bool muted = board.force_amplifier_mute();
        const bool closed = codec.speaker_off();
        return muted && closed;
      },
      // No writes without independently verified board, rails, and reset.
      [&codec, &board, &owner_approved, &physical_stop]() {
        if (physical_stop.load() || !owner_approved.load() ||
            !board.exact_board_confirmed() ||
            !board.power_rails_confirmed() ||
            !board.amplifier_reset_confirmed())
          return false;
        return codec.prepare(true, true, true);
      },
      [&codec, &owner_approved, &physical_stop]() {
        return !physical_stop.load() && owner_approved.load() &&
               codec.prepared() && codec.microphone_on();
      },
      [&board]() { return board.discard_microphone_dma(); },
      [&codec, &board, &owner_approved, &physical_stop]() {
        // Re-verify power/reset before every amplifier enable.
        if (physical_stop.load() || !owner_approved.load() ||
            !board.exact_board_confirmed() ||
            !board.power_rails_confirmed() ||
            !board.amplifier_reset_confirmed() ||
            !codec.prepared())
          return false;
        return codec.speaker_on_low_volume();
      },
      [&board, &owner_approved, &physical_stop]() {
        // This MUST be bound to a real completed-output witness.
        // No such physical witness is implemented in the HOLD firmware.
        return !physical_stop.load() && owner_approved.load() &&
               board.output_dma_drained_after_last_write();
      }};
}

}  // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
// K151 output power/reset and DMA-drain evidence. Pure policy; NO I2C/I2S.
// Source: pinned M5Stack StackChan board/stackchan.cc (AW9523, AXP2101).
// This is not a measurement system and cannot authorize the HOLD image.
#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>

namespace stackchan::standalone {

enum class OutputBlock : uint8_t {
  board_unknown,
  i2c_not_exclusive,
  rails_not_measured,
  aw9523_reset_unverified,
  amplifier_mute_unverified,
  physical_stop_unmeasured,
  tx_drain_telemetry_unavailable,
  hold_image_never_enables_audio,
};

struct K151OutputEvidence {
  bool exact_board_revision_verified = false;
  bool exclusive_i2c_ownership_verified = false;
  bool axp2101_rails_measured = false;
  bool aw9523_reset_sequence_verified = false;
  bool aw88298_hardware_mute_measured = false;
  bool independent_stop_latency_measured = false;
  bool dma_tx_empty_and_codec_idle_observable = false;
};

// No Boolean evidence, USB frame, or GPT request can enable audio in HOLD.
inline constexpr bool kK151PhysicalOutputEnabledInHoldImage = false;
inline constexpr OutputBlock assess_k151_output(const K151OutputEvidence& e) {
  if (!e.exact_board_revision_verified) return OutputBlock::board_unknown;
  if (!e.exclusive_i2c_ownership_verified) return OutputBlock::i2c_not_exclusive;
  if (!e.axp2101_rails_measured) return OutputBlock::rails_not_measured;
  if (!e.aw9523_reset_sequence_verified) return OutputBlock::aw9523_reset_unverified;
  if (!e.aw88298_hardware_mute_measured) return OutputBlock::amplifier_mute_unverified;
  if (!e.independent_stop_latency_measured) return OutputBlock::physical_stop_unmeasured;
  if (!e.dma_tx_empty_and_codec_idle_observable)
    return OutputBlock::tx_drain_telemetry_unavailable;
  return OutputBlock::hold_image_never_enables_audio;
}
inline constexpr bool kK151SafeDmaDrainDriverAvailable = false;
inline bool may_enable_k151_output(const K151OutputEvidence&) {
  return kK151PhysicalOutputEnabledInHoldImage && kK151SafeDmaDrainDriverAvailable;
}

// Bounded host model of a FUTURE independently observed transmission completion.
// A queued/accepted write alone is NOT drain evidence. This model uses only
// caller-supplied observations and DOES NOT sample hardware itself.
class DmaDrainLedger final {
 public:
  static constexpr size_t kMaxPcmFrames = 20 * 24000;  // 20s PCM16 mono

  bool begin(size_t frames, uint64_t monotonic_us) {
    if (started_ || faulted_ || frames == 0 || frames > kMaxPcmFrames)
      return fail();
    started_ = true;
    frames_ = frames;
    begin_us_ = monotonic_us;
    return true;
  }

  bool note_enqueued(size_t frames) {
    if (!started_ || faulted_ || confirmed_ || frames == 0 ||
        frames > frames_ - enqueued_)
      return fail();
    enqueued_ += frames;
    return true;
  }

  // Both signals MUST originate from independently validated hardware
  // observers. Calling this with fabricated booleans is NOT a valid proof.
  bool confirm(bool dma_tx_empty, bool codec_output_idle,
               bool verified_sample_clock, bool stop_latched,
               uint64_t observed_us) {
    if (!started_ || faulted_ || confirmed_ || stop_latched ||
        !dma_tx_empty || !codec_output_idle || !verified_sample_clock ||
        enqueued_ != frames_ || observed_us < begin_us_)
      return fail();
    const uint64_t required_us =
        static_cast<uint64_t>(frames_) * 1000000ULL / 24000ULL;
    if (observed_us - begin_us_ < required_us) return fail();
    confirmed_ = true;
    return true;
  }

  bool confirmed() const { return confirmed_ && !faulted_; }
  bool faulted() const { return faulted_; }

 private:
  bool fail() {
    faulted_ = true;  // No automatic reset or repeated output admission.
    confirmed_ = false;
    return false;
  }
  uint64_t begin_us_ = 0;
  size_t frames_ = 0, enqueued_ = 0;
  bool started_ = false, confirmed_ = false, faulted_ = false;
};

} // namespace stackchan::standalone

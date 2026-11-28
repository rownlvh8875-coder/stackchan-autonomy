// SPDX-License-Identifier: MIT
#pragma once

#include "audio_wipe.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <optional>

namespace stackchan::standalone {

// Diagnostic analysis of a contiguous 24 kHz, four-slot PCM16 stream. The
// sample origin and STOP position must come from the same verified timebase.
// This class cannot establish clock alignment or a physical pin transition.
class K151AecStopProbe final {
 public:
  static constexpr uint32_t kSampleRate = 24'000;
  static constexpr uint32_t kSlots = 4;
  static constexpr uint32_t kReferenceSlot = 1;
  static constexpr uint32_t kFrameBits = kSlots * 16;
  static constexpr uint32_t kBclkHz = kSampleRate * kFrameBits;
  static constexpr uint32_t kFramesPerBlock = 240;
  static constexpr uint32_t kMaxFrames = 3 * kSampleRate;

  struct Cutoff {
    uint32_t stop_frame;
    uint32_t first_possible_frame; // Start of the last tone-bearing window.
    uint32_t quiet_by_frame;       // End of the first window of sustained quiet.
  };

  // Takes ownership of only the transient block contents. Other slots are
  // never read by the analyzer, and the whole block is wiped on every exit.
  bool observe(uint32_t first, std::span<int16_t> block) {
    ScopedPcmWipe wipe{block};
    if (phase_ == Phase::fault || block.size() != kFramesPerBlock * kSlots ||
        first != next_frame_ || first > kMaxFrames - kFramesPerBlock ||
        (phase_ == Phase::baseline && next_frame_ >= kBaselineFrames))
      return reject();
    for (uint32_t offset = 0; offset < kFramesPerBlock; offset += kWindowFrames) {
      const auto view = block.subspan(offset * kSlots, kWindowFrames * kSlots);
      if (!observe_window(first + offset, view)) return reject();
    }
    next_frame_ += kFramesPerBlock;
    return true;
  }

  bool begin_tone(uint32_t planned_tone_end) {
    if (phase_ != Phase::baseline || next_frame_ != kBaselineFrames ||
        planned_tone_end <= next_frame_ + kAfterStopFrames || planned_tone_end > kMaxFrames)
      return reject();
    // Use the highest observed quiet-window energy, with a 6 dB margin.
    // These are diagnostic criteria for the synthetic stimulus only.
    quiet_limit_ = 4 * std::max<uint64_t>(baseline_energy_, 1);
    planned_end_frame_ = planned_tone_end;
    phase_ = Phase::tone;
    return true;
  }

  // Supply the frame before analyzing its DMA block. A task/USB receipt time
  // is not a substitute for a sample index synchronized to this stream.
  bool mark_stop(uint32_t frame) {
    if (phase_ != Phase::tone || tone_run_ < kStableToneWindows ||
        frame < next_frame_ || frame - next_frame_ >= kFramesPerBlock ||
        frame > planned_end_frame_ - kAfterStopFrames)
      return reject();
    stop_frame_ = frame;
    phase_ = Phase::after_stop;
    return true;
  }

  std::optional<Cutoff> cutoff() const {
    if (phase_ != Phase::after_stop || next_frame_ < stop_frame_ + kAfterStopFrames ||
        quiet_run_ < kStableQuietWindows ||
        quiet_start_ + kStableQuietWindows * kWindowFrames > planned_end_frame_)
      return std::nullopt;
    return Cutoff{stop_frame_, last_tone_frame_, quiet_start_ + kWindowFrames};
  }

 private:
  enum class Phase { baseline, tone, after_stop, fault };
  static constexpr uint32_t kWindowFrames = 24; // One 1 kHz period and 1 ms at 24 kHz.
  static constexpr uint32_t kBaselineFrames = 3 * kFramesPerBlock;
  static constexpr uint32_t kAfterStopFrames = 5 * kFramesPerBlock;
  static constexpr uint32_t kStableToneWindows = 10;
  static constexpr uint32_t kStableQuietWindows = 10;
  static constexpr std::array<int, kWindowFrames> kSine{
      0, 17, 32, 45, 55, 62, 64, 62, 55, 45, 32, 17,
      0, -17, -32, -45, -55, -62, -64, -62, -55, -45, -32, -17};

  bool observe_window(uint32_t first, std::span<const int16_t> window) {
    uint64_t energy = 0;
    int64_t sine = 0, cosine = 0;
    for (uint32_t i = 0; i < kWindowFrames; ++i) {
      const int64_t sample = window[i * kSlots + kReferenceSlot];
      if (sample == std::numeric_limits<int16_t>::min() ||
          sample == std::numeric_limits<int16_t>::max())
        return false;
      energy += static_cast<uint64_t>(sample * sample);
      sine += sample * kSine[i];
      cosine += sample * kSine[(i + kWindowFrames / 4) % kWindowFrames];
    }
    if (phase_ == Phase::baseline) {
      baseline_energy_ = std::max(baseline_energy_, energy);
      return true;
    }
    // Require both energy above the quiet floor and coherent energy near the
    // stimulus frequency. The two correlations allow arbitrary signal phase.
    const bool tone = energy >= 16 * quiet_limit_ &&
        static_cast<uint64_t>(sine * sine + cosine * cosine) >=
            energy * kWindowFrames * 1024;
    if (tone) last_tone_frame_ = first;

    if (phase_ == Phase::tone || first + kWindowFrames <= stop_frame_) {
      if (!tone && tone_run_ >= kStableToneWindows) return false;
      tone_run_ = tone ? tone_run_ + 1 : 0;
      return true;
    }
    if (energy <= quiet_limit_) {
      if (quiet_run_++ == 0) quiet_start_ = first;
    } else {
      quiet_run_ = 0;
    }
    return true;
  }

  bool reject() {
    phase_ = Phase::fault;
    return false;
  }

  Phase phase_ = Phase::baseline;
  uint32_t next_frame_ = 0;
  uint32_t planned_end_frame_ = 0;
  uint32_t stop_frame_ = 0;
  uint32_t last_tone_frame_ = 0;
  uint32_t tone_run_ = 0;
  uint32_t quiet_run_ = 0;
  uint32_t quiet_start_ = 0;
  uint64_t baseline_energy_ = 0;
  uint64_t quiet_limit_ = 0;
};

}  // namespace stackchan::standalone

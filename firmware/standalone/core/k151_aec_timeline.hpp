// SPDX-License-Identifier: MIT
#pragma once

#include "k151_aec_stop_probe.hpp"

namespace stackchan::standalone {

// An RX EOF callback and the display STOP sampler both use esp_timer.
// Their delivery timestamps bracket a descriptor; they are not per-sample
// hardware timestamps. Never infer an exact STOP sample from the CPU clock.
class K151AecTimeline final {
 public:
  struct Bracket {
    uint32_t first_frame;
    uint32_t end_frame; // Exclusive.
    int64_t before_us;
    int64_t after_us;
  };

  bool accept(uint32_t first_frame, int64_t eof_us) {
    constexpr auto block = K151AecStopProbe::kFramesPerBlock;
    if (!valid_ || first_frame != next_frame_ || eof_us < 0 ||
        first_frame > K151AecStopProbe::kMaxFrames - block ||
        (last_us_ >= 0 && (eof_us <= last_us_ || eof_us - last_us_ < 8'000 ||
                         eof_us - last_us_ > 12'000))) {
      valid_ = false;
      return false;
    }
    previous_us_ = last_us_;
    last_us_ = eof_us;
    next_frame_ += block;
    return true;
  }

  [[nodiscard]] std::optional<Bracket> stop_bracket(int64_t sampled_us) const {
    if (!valid_ || previous_us_ < 0 || sampled_us < previous_us_ || sampled_us >= last_us_)
      return std::nullopt;
    return Bracket{next_frame_ - K151AecStopProbe::kFramesPerBlock, next_frame_,
                   previous_us_, last_us_};
  }

  [[nodiscard]] bool valid() const { return valid_; }
  [[nodiscard]] uint32_t next_frame() const { return next_frame_; }

 private:
  uint32_t next_frame_ = 0;
  int64_t previous_us_ = -1;
  int64_t last_us_ = -1;
  bool valid_ = true;
};

}  // namespace stackchan::standalone

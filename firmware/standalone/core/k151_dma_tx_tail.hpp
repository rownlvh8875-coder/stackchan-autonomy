// SPDX-License-Identifier: MIT
#pragma once

#include <cstddef>
#include <cstdint>

namespace stackchan::standalone {

// Observe a full rotation of the fixed K151 DMA ring after the final write.
// The first callback might already be in flight when the owner arms the fence.
// Require a second completion of that first buffer, after every other buffer.
// This observes DMA only. The ESP-IDF port serializes ISR and task access
// with a DRAM-backed critical section, including with PSRAM enabled.
class DmaTxTail final {
 public:
  static constexpr size_t kDescriptorCount = 6;
  static constexpr size_t kFramesPerDescriptor = 240;
  enum class Result : uint32_t { idle, waiting, observed, failed };

  bool arm(size_t descriptor_bytes, int64_t started_us) {
    constexpr size_t mono_bytes = kFramesPerDescriptor * sizeof(int16_t);
    if (started_us < 0 || (phase_ != Result::idle && phase_ != Result::observed) ||
        (descriptor_bytes != mono_bytes && descriptor_bytes != 2 * mono_bytes))
      return false;
    descriptor_bytes_ = descriptor_bytes;
    seen_ = 0;
    started_us_ = previous_us_ = started_us;
    phase_ = Result::waiting;
    return true;
  }

  // One DMA ISR owns the observations. It retains identities only, without
  // retaining or reading the descriptor PCM. Keep this inline in the IRAM shim.
  [[gnu::always_inline]] void on_sent(const void* buffer, size_t bytes) noexcept {
    if (phase_ != Result::waiting) return;
    if (!buffer || bytes != descriptor_bytes_) {
      phase_ = Result::failed;
      return;
    }
    if (seen_ == kDescriptorCount) {
      phase_ = buffer == buffers_[0] ? Result::observed : Result::failed;
      return;
    }
    for (size_t i = 0; i < seen_; ++i) {
      if (buffers_[i] == buffer) {
        phase_ = Result::failed;
        return;
      }
    }
    buffers_[seen_++] = buffer;
  }

  template<class ReadClock>
  Result poll(const ReadClock& clock) {
    // Read the clock after sampling progress so late EOF cannot win a race
    // against a stale pre-deadline sample.
    const auto state = phase_;
    if (state == Result::idle || state == Result::failed) return state;
    const auto now_us = clock();
    if (now_us < previous_us_ || now_us - started_us_ >= kDeadlineUs) {
      abandon();
      return Result::failed;
    }
    previous_us_ = now_us;
    return state;
  }
  void abandon() { phase_ = Result::failed; }

  // The driver has removed the callback. No task may call arm during release.
  void reset_after_release() { phase_ = Result::idle; }

 private:
  static constexpr int64_t kDeadlineUs = 100'000;
  Result phase_ = Result::idle;
  const void* buffers_[kDescriptorCount]{};
  size_t descriptor_bytes_ = 0;
  size_t seen_ = 0;
  int64_t started_us_ = 0;
  int64_t previous_us_ = 0;
};

} // namespace stackchan::standalone

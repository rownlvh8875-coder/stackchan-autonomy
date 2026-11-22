// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace stackchan::standalone {

// Observe a full rotation of the fixed K151 DMA ring after the final write.
// The first callback might already be in flight when the owner arms the fence.
// Require a second completion of that first buffer, after every other buffer.
// This is evidence about DMA, not about the codec's analog output.
class DmaTxTail final {
 public:
  static constexpr size_t kDescriptorCount = 6;
  static constexpr size_t kFramesPerDescriptor = 240;
  enum class Result : uint32_t { idle, waiting, observed, failed };

  bool arm(size_t descriptor_bytes, int64_t started_us) {
    constexpr size_t mono_bytes = kFramesPerDescriptor * sizeof(int16_t);
    const auto state = result();
    if (started_us < 0 || (state != Result::idle && state != Result::observed) ||
        (descriptor_bytes != mono_bytes && descriptor_bytes != 2 * mono_bytes))
      return false;
    descriptor_bytes_ = descriptor_bytes;
    seen_ = 0;
    started_us_ = previous_us_ = started_us;
    phase_.store(Result::waiting, std::memory_order_release);
    return true;
  }

  // One DMA ISR owns the observations. It retains identities only, without
  // retaining or reading the descriptor PCM. Keep this inline in the IRAM shim.
  [[gnu::always_inline]] void on_sent(const void* buffer, size_t bytes) noexcept {
    if (phase_.load(std::memory_order_acquire) != Result::waiting ||
        abandoned_.load(std::memory_order_acquire))
      return;
    if (!buffer || bytes != descriptor_bytes_) {
      phase_.store(Result::failed, std::memory_order_release);
      return;
    }
    if (seen_ == kDescriptorCount) {
      phase_.store(buffer == buffers_[0] ? Result::observed : Result::failed,
                   std::memory_order_release);
      return;
    }
    for (size_t i = 0; i < seen_; ++i) {
      if (buffers_[i] == buffer) {
        phase_.store(Result::failed, std::memory_order_release);
        return;
      }
    }
    buffers_[seen_++] = buffer;
  }

  template<class ReadClock>
  Result poll(const ReadClock& clock) {
    // Read the clock after sampling progress so late EOF cannot win a race
    // against a stale pre-deadline sample.
    const auto state = result();
    if (state == Result::idle || state == Result::failed) return state;
    const auto now_us = clock();
    if (now_us < previous_us_ || now_us - started_us_ >= kDeadlineUs) {
      abandon();
      return Result::failed;
    }
    previous_us_ = now_us;
    return state;
  }
  void abandon() { abandoned_.store(true, std::memory_order_release); }

  // The driver has removed the callback. No task may call arm during release.
  void reset_after_release() {
    phase_.store(Result::idle, std::memory_order_relaxed);
    abandoned_.store(false, std::memory_order_relaxed);
  }

 private:
  static constexpr int64_t kDeadlineUs = 100'000;
  static_assert(std::atomic<Result>::is_always_lock_free);
  static_assert(std::atomic_bool::is_always_lock_free);
  Result result() const {
    return abandoned_.load(std::memory_order_acquire) ? Result::failed :
           phase_.load(std::memory_order_acquire);
  }
  std::atomic<Result> phase_{Result::idle};
  std::atomic_bool abandoned_{false};
  const void* buffers_[kDescriptorCount]{};
  size_t descriptor_bytes_ = 0;
  size_t seen_ = 0;
  int64_t started_us_ = 0;
  int64_t previous_us_ = 0;
};

} // namespace stackchan::standalone

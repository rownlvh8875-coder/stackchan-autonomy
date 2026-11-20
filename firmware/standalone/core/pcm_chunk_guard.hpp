// SPDX-License-Identifier: MIT
// Host-testable bounded PCM16 streaming guard; NO physical I2S or DMA proof.
#pragma once

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>

namespace stackchan::standalone {

inline constexpr size_t kPcmOutputChunkSamples = 240; // 10ms at 24kHz
inline constexpr size_t kPcmOutputMaxSamples = 20 * 24000; // <=20s
inline constexpr uint64_t kPcmOutputDeadlineMs = 25000; // Upper bound on loop admission

// Writer returns true only for a complete synchronous chunk write.
// Clock returns a monotonic millisecond timestamp, or nullopt on failure.
// A successful write STILL DOES NOT prove physical DMA/codec drain.
// A blocked Writer cannot be interrupted by this synchronous guard; a real
// deployment needs independently measured physical STOP and mute.
template <typename Writer, typename Clock>
std::optional<uint64_t> stream_pcm_chunks_guarded(
    std::span<const int16_t> mono24k, uint64_t started_ms,
    const std::atomic_bool& physical_stop, const std::atomic_bool& consent,
    Writer&& writer, Clock&& clock) {
  if (mono24k.empty() || mono24k.size() > kPcmOutputMaxSamples ||
      started_ms > std::numeric_limits<uint64_t>::max() - kPcmOutputDeadlineMs ||
      physical_stop.load() || !consent.load())
    return std::nullopt;
  const uint64_t deadline_ms = started_ms + kPcmOutputDeadlineMs;
  uint64_t last_ms = started_ms;
  for (size_t pos = 0; pos < mono24k.size();) {
    if (physical_stop.load() || !consent.load()) return std::nullopt;
    const std::optional<uint64_t> before = clock();
    if (!before || *before < last_ms || *before > deadline_ms)
      return std::nullopt;
    last_ms = *before;
    const size_t n = std::min(kPcmOutputChunkSamples, mono24k.size() - pos);
    if (!writer(mono24k.subspan(pos, n)))
      return std::nullopt;
    pos += n;
    // Observe time and cancellation again AFTER each synchronous write.
    if (physical_stop.load() || !consent.load()) return std::nullopt;
    const std::optional<uint64_t> after = clock();
    if (!after || *after < last_ms || *after > deadline_ms)
      return std::nullopt;
    last_ms = *after;
  }
  return last_ms;
}

} // namespace stackchan::standalone

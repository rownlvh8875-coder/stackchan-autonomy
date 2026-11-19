// SPDX-License-Identifier: MIT
// Conservative, OFFLINE memory-readiness preflight. Never authorizes flashing.
// ESP32-S3 memory observations and actual vector allocator behavior are
// UNKNOWN in the HOLD image; callers must not forge verification flags.
#pragma once

#include "offline_voice_cycle.hpp"

#include <cstddef>

namespace stackchan::standalone {

// Raw peak bytes only: one 8s question may coexist with one 20s TTS buffer.
// std::vector capacity, TLS, JSON, wake scratch and decoder memory ADD overhead.
inline constexpr size_t kQuestionPcmBytes =
    OfflineVoiceCycle::kMaxRecordedFrames * sizeof(int16_t); // 384000B
inline constexpr size_t kSynthPcmBytes =
    OfflineVoiceCycle::kMaxSynthFrames * sizeof(int16_t);   // 960000B
inline constexpr size_t kRawConcurrentPcmBytes =
    kQuestionPcmBytes + kSynthPcmBytes;                     // 1344000B

// Deliberately conservative *policy margins*, not measured K151 heap usage.
inline constexpr size_t kUnmeasuredOverheadReserve = 512 * 1024;
inline constexpr size_t kRequiredPsramFree =
    kRawConcurrentPcmBytes + kUnmeasuredOverheadReserve;
inline constexpr size_t kRequiredLargestPsramBlock =
    kSynthPcmBytes + 128 * 1024;
inline constexpr size_t kRequiredInternalFree = 128 * 1024;
inline constexpr size_t kRequiredLargestInternalBlock = 32 * 1024;

struct AudioMemorySnapshot {
  bool live_capability_metrics_measured = false;
  bool pcm_allocator_proven_psram = false;
  bool simultaneous_recording_and_tts_measured = false;
  size_t psram_free = 0;
  size_t psram_largest_block = 0;
  size_t internal_free = 0;
  size_t internal_largest_block = 0;
};

enum class MemoryPreflight {
  not_measured,
  allocator_unverified,
  concurrent_peak_unmeasured,
  psram_free_insufficient,
  psram_contiguous_insufficient,
  internal_free_insufficient,
  internal_contiguous_insufficient,
  diagnostic_budget_satisfied_not_install_approval,
};

inline MemoryPreflight check_audio_memory_preflight(
    const AudioMemorySnapshot& snapshot) {
  if (!snapshot.live_capability_metrics_measured)
    return MemoryPreflight::not_measured;
  if (!snapshot.pcm_allocator_proven_psram)
    return MemoryPreflight::allocator_unverified;
  if (!snapshot.simultaneous_recording_and_tts_measured)
    return MemoryPreflight::concurrent_peak_unmeasured;
  if (snapshot.psram_free < kRequiredPsramFree)
    return MemoryPreflight::psram_free_insufficient;
  if (snapshot.psram_largest_block < kRequiredLargestPsramBlock)
    return MemoryPreflight::psram_contiguous_insufficient;
  if (snapshot.internal_free < kRequiredInternalFree)
    return MemoryPreflight::internal_free_insufficient;
  if (snapshot.internal_largest_block < kRequiredLargestInternalBlock)
    return MemoryPreflight::internal_contiguous_insufficient;
  return MemoryPreflight::diagnostic_budget_satisfied_not_install_approval;
}

// No externally supplied booleans, measurements or fabricated simulator
// readings may override the hard K151 output/flash HOLD.
inline constexpr bool kAudioMemoryReadinessCanAuthorizeInstall = false;

} // namespace stackchan::standalone

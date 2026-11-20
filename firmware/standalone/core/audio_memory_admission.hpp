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

// Observations must come from the local owner while the *actual model remains
// allocated*. Its memory has already been subtracted from after_model free
// bytes; do not substitute app size or subtract model flash bytes as RAM.
// The combined watermark includes question, TLS/JSON and TTS allocations with
// their actual allocator capabilities, not just the nominal raw PCM sizes.
struct NativeAudioMemorySnapshot {
  AudioMemorySnapshot after_model;
  bool model_resident_during_measurement = false;
  bool question_tls_tts_peak_measured = false;
  size_t concurrent_internal_peak = 0;
  size_t concurrent_psram_peak = 0;
};
enum class NativeMemoryPreflight {
  model_unmeasured, combined_peak_unmeasured, invalid_peak, audio_budget_rejected,
  internal_peak_insufficient, psram_peak_insufficient, diagnostic_ready,
};
inline NativeMemoryPreflight check_native_audio_memory_preflight(
    const NativeAudioMemorySnapshot& e) {
  if (!e.model_resident_during_measurement)
    return NativeMemoryPreflight::model_unmeasured;
  if (!e.question_tls_tts_peak_measured)
    return NativeMemoryPreflight::combined_peak_unmeasured;
  if (e.concurrent_internal_peak == 0 || e.concurrent_psram_peak < kRawConcurrentPcmBytes)
    return NativeMemoryPreflight::invalid_peak;
  if (check_audio_memory_preflight(e.after_model) !=
      MemoryPreflight::diagnostic_budget_satisfied_not_install_approval)
    return NativeMemoryPreflight::audio_budget_rejected;
  // Subtraction after the baseline check avoids overflow with corrupt metrics.
  if (e.concurrent_internal_peak > e.after_model.internal_free - 32 * 1024)
    return NativeMemoryPreflight::internal_peak_insufficient;
  if (e.concurrent_psram_peak > e.after_model.psram_free - 128 * 1024)
    return NativeMemoryPreflight::psram_peak_insufficient;
  return NativeMemoryPreflight::diagnostic_ready;
}

} // namespace stackchan::standalone

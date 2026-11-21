// SPDX-License-Identifier: MIT
#include "audio_memory_admission.hpp"
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

int main() {
  static_assert(kQuestionPcmBytes == 384000);
  static_assert(kSynthPcmBytes == 960000);
  static_assert(kRawConcurrentPcmBytes == 1344000);
  static_assert(kConcurrentSpeechPayloadBytes == 2304000);
  static_assert(kRequiredPsramFree == 2304000 + 512 * 1024);
  static_assert(!kAudioMemoryReadinessCanAuthorizeInstall);

  NativeAudioMemorySnapshot native;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::model_unmeasured);
  native.model_resident_during_measurement=true;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::combined_peak_unmeasured);
  native.question_tls_tts_peak_measured=true;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::invalid_peak);
  native.concurrent_psram_peak=kRawConcurrentPcmBytes;
  native.concurrent_internal_peak=32*1024;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::invalid_peak);
  native.concurrent_psram_peak=kConcurrentSpeechPayloadBytes;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::audio_budget_rejected);
  native.after_model={true,true,true,kRequiredPsramFree,kRequiredLargestPsramBlock,
                      kRequiredInternalFree,kRequiredLargestInternalBlock};
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::diagnostic_ready);
  native.concurrent_internal_peak=kRequiredInternalFree;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::internal_peak_insufficient);
  native.concurrent_internal_peak=32*1024;
  native.concurrent_psram_peak=kRequiredPsramFree;
  assert(check_native_audio_memory_preflight(native)==NativeMemoryPreflight::psram_peak_insufficient);

  AudioMemorySnapshot e;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::not_measured);
  e.live_capability_metrics_measured = true;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::allocator_unverified);
  e.pcm_allocator_proven_psram = true;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::concurrent_peak_unmeasured);
  e.simultaneous_recording_and_tts_measured = true;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::psram_free_insufficient);

  e.psram_free = kRequiredPsramFree;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::psram_contiguous_insufficient);
  e.psram_largest_block = kRequiredLargestPsramBlock;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::internal_free_insufficient);
  e.internal_free = kRequiredInternalFree;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::internal_contiguous_insufficient);
  e.internal_largest_block = kRequiredLargestInternalBlock;
  assert(check_audio_memory_preflight(e) ==
      MemoryPreflight::diagnostic_budget_satisfied_not_install_approval);

  // Even all manually asserted inputs are not an authorization.
  assert(!kAudioMemoryReadinessCanAuthorizeInstall);
  e.psram_largest_block -= 1;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::psram_contiguous_insufficient);
  e.psram_largest_block += 1;
  e.psram_free -= 1;
  assert(check_audio_memory_preflight(e) == MemoryPreflight::psram_free_insufficient);
  std::cout << "audio memory headroom policy: PASS (synthetic only)\n";
}

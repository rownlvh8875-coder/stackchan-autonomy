// SPDX-License-Identifier: MIT
#include "audio_memory_admission.hpp"
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

int main() {
  static_assert(kQuestionPcmBytes == 384000);
  static_assert(kSynthPcmBytes == 960000);
  static_assert(kRawConcurrentPcmBytes == 1344000);
  static_assert(kRequiredPsramFree == 1344000 + 512 * 1024);
  static_assert(!kAudioMemoryReadinessCanAuthorizeInstall);

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

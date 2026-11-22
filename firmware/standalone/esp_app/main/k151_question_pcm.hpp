// SPDX-License-Identifier: MIT
#pragma once

#include "question_capture.hpp"

#include <esp_heap_caps.h>
#include <esp_memory_utils.h>

namespace stackchan::standalone {

// Supply this allocator to the K151 turn coordinator before arming the mic.
// A failed allocation or placement check must never spill into internal RAM.
inline QuestionCapture::Buffer k151_allocate_question_pcm() noexcept {
  constexpr size_t count = QuestionCapture::kMaxSamples;
  QuestionCapture::Buffer pcm{
      static_cast<int16_t*>(heap_caps_malloc(count * sizeof(int16_t),
                                            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)),
      [](int16_t* ptr) { heap_caps_free(ptr); }};
  if (pcm && (!esp_ptr_external_ram(pcm.get()) ||
              !esp_ptr_external_ram(&pcm[count - 1])))
    pcm.reset();
  return pcm;
}

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
#include <cstdint>
#include <span>

extern const uint8_t model_start[] asm("_binary_srmodels_bin_start");
extern const uint8_t model_end[] asm("_binary_srmodels_bin_end");

namespace stackchan::standalone {
std::span<const uint8_t> linked_mic_trial_model() {
  return {model_start, reinterpret_cast<uintptr_t>(model_end) -
                       reinterpret_cast<uintptr_t>(model_start)};
}
}

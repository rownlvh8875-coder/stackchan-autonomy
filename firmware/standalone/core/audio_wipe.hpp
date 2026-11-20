// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <span>
namespace stackchan::standalone {
// Same volatile-store pattern as wipe_secret: retained even at end of lifetime.
// Erases owned PCM, not copies in registers or the vendor model's allocation.
inline void wipe_pcm(std::span<int16_t> pcm) noexcept {
  volatile int16_t* const ptr=pcm.data();
  for(size_t i=0;i<pcm.size();++i)ptr[i]=0;
}
} // namespace stackchan::standalone

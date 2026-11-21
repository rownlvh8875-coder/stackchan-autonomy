// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <cstddef>
#include <span>
namespace stackchan::standalone {
// Same volatile-store pattern as wipe_secret: retained even at end of lifetime.
// Erases owned PCM, not copies in registers or the vendor model's allocation.
inline void wipe_pcm(std::span<int16_t> pcm) noexcept {
  volatile int16_t* const ptr=pcm.data();
  for(size_t i=0;i<pcm.size();++i)ptr[i]=0;
}
inline void wipe_audio_bytes(std::span<uint8_t> bytes) noexcept {
  volatile uint8_t* const ptr = bytes.data();
  for (size_t i = 0; i < bytes.size(); ++i) ptr[i] = 0;
}
class ScopedPcmWipe final {
 public:
  explicit ScopedPcmWipe(std::span<int16_t> pcm) noexcept : pcm_(pcm) {}
  ~ScopedPcmWipe() { wipe_pcm(pcm_); }
  ScopedPcmWipe(const ScopedPcmWipe&) = delete;
  ScopedPcmWipe& operator=(const ScopedPcmWipe&) = delete;
 private:
  std::span<int16_t> pcm_;
};
} // namespace stackchan::standalone

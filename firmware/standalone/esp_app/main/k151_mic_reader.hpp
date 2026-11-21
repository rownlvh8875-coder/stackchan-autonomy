// SPDX-License-Identifier: MIT
// Dormant build-only wiring to guarded K151 codec: never constructed by app_main.
#pragma once

#include "k151_codec_port.hpp"
#include "mic_frame_bridge.hpp"

namespace stackchan::standalone {
class K151MicReader final : public MonoMicReader {
 public:
  explicit K151MicReader(K151CodecPort& codec) : codec_(codec) {}
  bool read_10ms(std::span<int16_t> pcm240) override {
    // Refuse wrong size, unprepared or faulted hardware before codec I/O.
    const bool ok = pcm240.size() == 240 && codec_.prepared() &&
                    codec_.capture_mono_24k(pcm240);
    if (!ok) wipe_pcm(pcm240);
    return ok;
  }
 private:
  K151CodecPort& codec_;
};
} // namespace stackchan::standalone

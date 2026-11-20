// SPDX-License-Identifier: MIT
// Model boundary only. No model, microphone or external service is started here.
#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
namespace stackchan::standalone {
struct NativeWakeFormat {
  int sample_rate_hz=0;
  size_t chunk_samples=0;
  int channels=0;
  int bits_per_sample=0;
  bool operator==(const NativeWakeFormat&) const=default;
};
enum class NativeWakeResult {none,detected,error};
class NativeWakePort {
 public:
  virtual ~NativeWakePort()=default;
  virtual bool ready() const=0;
  virtual NativeWakeFormat format() const=0;
  virtual NativeWakeResult detect(std::span<int16_t> pcm16k)=0;
  virtual bool reset()=0;
};
} // namespace stackchan::standalone

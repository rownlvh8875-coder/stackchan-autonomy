// SPDX-License-Identifier: MIT
// Fixed-memory causal24k PCM16 ->16k PCM16. No audio IO or recognition.
#pragma once
#include "audio_wipe.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>
namespace stackchan::standalone {
class StreamingPcm24To16 final {
 public:
  StreamingPcm24To16() {
    constexpr float pi=3.14159265358979323846f;
    for (int phase=0; phase<2; ++phase) {
      float sum=0;
      for (int j=-16; j<=16; ++j) {
        const float x=static_cast<float>(j)-phase*0.5f;
        const float z=0.60f*x;
        const float sinc=std::abs(z)<1.e-6f?1.f:std::sin(pi*z)/(pi*z);
        const float value=0.60f*sinc*0.5f*(1.f+std::cos(pi*x/16.5f));
        kernel_[phase][j+16]=value;sum+=value;
      }
      for (float& w:kernel_[phase]) w/=sum;
    }
  }
  ~StreamingPcm24To16() {reset();}
  bool process(std::span<const int16_t> input,std::span<int16_t> output) {
    if (input.size()!=240 || output.size()!=160) {
      wipe_pcm(output);reset();return false;
    }
    size_t written=0;
    for (const int16_t sample:input) {
      history_[position_]=sample;
      if (phase_<2) {
        float acc=0;
        for (size_t j=0;j<33;++j)
          acc+=kernel_[phase_][j]*history_[(position_+1+j)%33];
        output[written++]=static_cast<int16_t>(std::clamp(std::round(acc),-32768.f,32767.f));
      }
      phase_=(phase_+1)%3;
      position_=(position_+1)%33;
    }
    return written==160;
  }
  void reset() {wipe_pcm(history_);position_=0;phase_=0;}
 private:
  std::array<std::array<float,33>,2> kernel_{};
  std::array<int16_t,33> history_{};
  size_t position_=0,phase_=0;
};
} // namespace stackchan::standalone

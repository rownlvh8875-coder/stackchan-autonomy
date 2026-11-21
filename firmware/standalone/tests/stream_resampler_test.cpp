// SPDX-License-Identifier: MIT
// Mathematical PCM only. Never reads a microphone or calls a speech model.
#include "stream_resampler.hpp"
#include "wake_features.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
#include <string_view>
#include <vector>
using namespace stackchan::standalone;

std::vector<int16_t> converted_tone(float hz) {
  StreamingPcm24To16 resampler;
  std::array<int16_t,240> input{};
  std::array<int16_t,160> output{};
  std::vector<int16_t> all;
  for (int block=0; block<20; ++block) {
    for (size_t i=0; i<input.size(); ++i)
      input[i]=static_cast<int16_t>(10000*std::sin(2*kPi*hz*(block*240+i)/24000.f));
    assert(resampler.process(input,output));
    all.insert(all.end(),output.begin(),output.end());
  }
  return all;
}
double rms_tail(const std::vector<int16_t>& data) {
  double sum=0;
  for (size_t i=640; i<data.size(); ++i) sum+=double(data[i])*data[i];
  return std::sqrt(sum/double(data.size()-640));
}
int main(int argc,char** argv) {
  assert(argc==2);
  const std::string_view test=argv[1];
  if (test=="count_dc") {
    StreamingPcm24To16 r;
    std::array<int16_t,240> in{}; in.fill(8000);
    std::array<int16_t,162> guarded{}; guarded.fill(12345);
    for (int n=0; n<100; ++n) {
      assert(r.process(in,std::span(guarded).subspan(1,160)));
      assert(guarded.front()==12345 && guarded.back()==12345);
      if (n>0) for (size_t i=1; i<=160; ++i) assert(std::abs(guarded[i]-8000)<=1);
    }
  } else if (test=="batch_reference") {
    std::vector<int16_t> raw(24000),padded(16,0),streamed;
    uint32_t rng=19;
    for (auto& v:raw) { rng=1664525U*rng+1013904223U; v=static_cast<int16_t>((rng>>16U)%12001-6000); }
    padded.insert(padded.end(),raw.begin(),raw.end());
    const auto reference=resample_24k_to_16k(padded);
    assert(reference);
    StreamingPcm24To16 r;
    std::array<int16_t,160> out{};
    for (size_t offset=0; offset<raw.size(); offset+=240) {
      assert(r.process(std::span(raw).subspan(offset,240),out));
      streamed.insert(streamed.end(),out.begin(),out.end());
    }
    assert(streamed.size()==16000);
    for (size_t i=0; i<streamed.size(); ++i)
      assert(std::abs(int(streamed[i])-int(std::lround((*reference)[i]*32768.f)))<=1);
  } else if (test=="anti_alias") {
    const auto low=converted_tone(1000),high=converted_tone(10000);
    assert(low.size()==3200 && high.size()==3200);
    assert(rms_tail(low)>6900 && rms_tail(low)<7200);
    assert(rms_tail(high)<rms_tail(low)*0.018); // >35dB stop-band rejection.
  } else if (test=="history_reset") {
    StreamingPcm24To16 r;
    std::array<int16_t,240> in{};
    std::array<int16_t,160> out{};
    in.back()=12000; assert(r.process(in,out));
    in.fill(0); assert(r.process(in,out));
    bool tail=false; for (size_t i=0; i<24; ++i) tail|=out[i]!=0;
    assert(tail); // Impulse straddles the10ms block boundary.
    in.back()=12000; assert(r.process(in,out));
    r.reset(); in.fill(0); assert(r.process(in,out));
    for (auto v:out) assert(v==0);
  } else if (test=="invalid_reset") {
    StreamingPcm24To16 r;
    std::array<int16_t,240> in{};
    std::array<int16_t,160> out{};
    in.back()=10000; assert(r.process(in,out));
    out.fill(12345);
    assert(!r.process(std::span(in).first(239),out));
    for (auto v:out) assert(v==0);
    in.fill(0); assert(r.process(in,out)); for (auto v:out) assert(v==0);
    assert(!r.process(in,std::span(out).first(159)));
    assert(!r.process({},out));
  } else if (test=="saturation") {
    StreamingPcm24To16 r;
    std::array<int16_t,240> in{};
    std::array<int16_t,160> out{};
    bool positive=false,negative=false;
    for (int n=0; n<5; ++n) {
      for (size_t i=0; i<240; ++i) in[i]=i<120?32767:-32768;
      assert(r.process(in,out));
      positive|=out[40]==32767; negative|=out[120]==-32768;
      assert(out[40]>32000 && out[120]<-32000);
    }
    assert(positive && negative);
  } else { assert(false); }
  std::cout << "stream-resampler case PASS\n";
}

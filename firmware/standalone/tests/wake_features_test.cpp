// SPDX-License-Identifier: MIT
#include "wake_features.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>

using namespace stackchan::standalone;

std::vector<int16_t> synth(float hz, bool quiet = false) {
  std::vector<int16_t> pcm(24000);  // one second
  for (size_t i=0; i<pcm.size(); ++i) {
    const float time=static_cast<float>(i)/24000.f;
    const float envelope=(time<0.12f || time>0.88f) ? 0.f : 1.f;
    const float signal=0.35f*envelope*(std::sin(2*kPi*hz*time) +
                                     0.4f*std::sin(2*kPi*hz*2.f*time));
    pcm[i]=static_cast<int16_t>((quiet ? 0.f : signal)*32767.f);
  }
  return pcm;
}

int main() {
  auto sine=synth(520.f);
  auto different=synth(900.f);
  auto silence=synth(0,true);
  assert(!wake_mfcc_from_24k(silence));
  assert(!wake_mfcc_from_24k(std::span<const int16_t>(sine).first(2399)));
  auto resampled=resample_24k_to_16k(sine);
  assert(resampled && resampled->size()==16000);
  auto a=wake_mfcc_from_24k(sine);
  auto b=wake_mfcc_from_24k(different);
  assert(a && b);
  assert(wake_dtw_distance(*a,*a)==0.f);
  assert(wake_dtw_distance(*a,*b)>0.f);
  std::array<WakeFeature,1> tmpl{*a};
  std::array<WakeFeature,5> positive{};
  std::array<WakeFeature,10> negative{};
  positive.fill(*a);
  negative.fill(*b);
  auto profile=calibrate_wake(tmpl,positive,negative);
  assert(profile && profile->accepts(*a) && !profile->accepts(*b));
  auto wire=encode_wake_profile(*profile);
  assert(wire && wire->size()<=4096);
  auto parsed=decode_wake_profile(*wire);
  assert(parsed && parsed->accepts(*a) && !parsed->accepts(*b));
  (*wire)[9] ^= 1;
  assert(!decode_wake_profile(*wire));
  negative.fill(*a);
  assert(!calibrate_wake(tmpl,positive,negative)); // no separation
  std::cout<<"wake features: PASS (anti-alias SRC, MFCC, DTW, profile, reject overlap)\n";
}

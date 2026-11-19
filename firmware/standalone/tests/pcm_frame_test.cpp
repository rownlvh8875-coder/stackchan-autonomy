#include "pcm_frame.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <vector>
using stackchan::standalone::extract_k151_mic0;
using stackchan::standalone::valid_pcm_playback;
int main() {
  std::array<int16_t, 480> stereo = {};
  for (size_t i = 0; i < 240; ++i) {
    stereo[2*i] = static_cast<int16_t>(i + 1);
    stereo[2*i+1] = static_cast<int16_t>(-1000 - static_cast<int>(i));
  }
  std::array<int16_t,240> mono = {};
  assert(extract_k151_mic0(stereo, mono));
  for (size_t i=0; i<240; ++i) assert(mono[i] == static_cast<int16_t>(i+1));
  assert(valid_pcm_playback(mono));
  std::array<int16_t, 2> one = {32,-300};
  std::array<int16_t, 1> single = {};
  assert(extract_k151_mic0(one, single) && single[0] == 32);
  assert(valid_pcm_playback(single));
  assert(!valid_pcm_playback(std::span<const int16_t>()));
  std::vector<int16_t> too_big(241, 1);
  assert(!valid_pcm_playback(too_big));
  std::array<int16_t,241> unsafe = {};
  assert(!extract_k151_mic0(stereo, unsafe));
  assert(!extract_k151_mic0(std::span<const int16_t>(stereo.data(), 478), mono));
  for (auto v: mono) assert(v == 0);
  std::cout << "pcm frame: PASS (lane isolation, bounded chunks, fail closed)\n";
}

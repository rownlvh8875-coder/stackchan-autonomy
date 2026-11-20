// SPDX-License-Identifier: MIT
// Offline-only energy trimming. This is NOT speech recognition or a K151 test.
#include "offline_wake_trim.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>

using namespace stackchan::standalone;

int main() {
  assert(!offline_trim_speech_24k(std::span<const int16_t>()));
  assert(!offline_trim_speech_24k(std::vector<int16_t>(2399, 0)));
  assert(!offline_trim_speech_24k(std::vector<int16_t>(72001, 1)));
  assert(!offline_trim_speech_24k(std::vector<int16_t>(24000, 0)));

  std::vector<int16_t> synthetic(24000, 0);
  for (size_t i = 5000; i < 18000; ++i) {
    const float phase = static_cast<float>(i) / 24000.f;
    synthetic[i] = static_cast<int16_t>(11000 * std::sin(
        2 * 3.14159265358979323846 * 400.f * phase));
  }
  auto trimmed = offline_trim_speech_24k(synthetic);
  assert(trimmed && trimmed->size() >= kTrimMinPcm24k);
  assert(trimmed->size() < synthetic.size());
  assert(std::any_of(trimmed->begin(), trimmed->end(),
                     [](int16_t x) { return x != 0; }));
  assert(offline_trim_speech_24k(synthetic) == trimmed);

  // High constant background leaves no meaningful speech-to-noise contrast.
  std::vector<int16_t> saturated(24000, 3000);
  assert(!offline_trim_speech_24k(saturated));

  // No random retry or implicit fallback if input is too contaminated.
  std::vector<int16_t> near_constant(24000);
  for (size_t i=0; i<near_constant.size(); ++i)
    near_constant[i] = static_cast<int16_t>(3000 + (i % 2 ? 300 : -300));
  assert(!offline_trim_speech_24k(near_constant));

  std::cout << "EXPERIMENTAL TRIM PASS (synthetic host-only)\n";
}

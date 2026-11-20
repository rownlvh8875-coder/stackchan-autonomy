// SPDX-License-Identifier: MIT
// Synthetic WAV and SWK1 fixtures; never uses or saves a user's recording.
#include "wake_features.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

using namespace stackchan::standalone;

std::vector<int16_t> synthetic(float hz) {
  std::vector<int16_t> data(24000);
  for (size_t i = 0; i < data.size(); ++i) {
    const float t = static_cast<float>(i) / 24000.f;
    const float gate = t < 0.12f || t > 0.88f ? 0.f : 1.f;
    const float value = gate * 0.32f *
        (std::sin(2*kPi*hz*t) + 0.3f*std::sin(4*kPi*hz*t));
    data[i] = static_cast<int16_t>(value * 32767.f);
  }
  return data;
}
std::vector<uint8_t> canonical_wav(const std::vector<int16_t>& samples) {
  std::vector<uint8_t> bytes{'R','I','F','F'};
  put32(bytes, static_cast<uint32_t>(36 + samples.size() * 2));
  bytes.insert(bytes.end(), {'W','A','V','E','f','m','t',' '});
  put32(bytes, 16);             // Canonical PCM format chunk.
  put16(bytes, 1);              // PCM.
  put16(bytes, 1);              // Mono.
  put32(bytes, 24000);
  put32(bytes, 48000);
  put16(bytes, 2);              // Block align.
  put16(bytes, 16);             // Bits per sample.
  bytes.insert(bytes.end(), {'d','a','t','a'});
  put32(bytes, static_cast<uint32_t>(samples.size() * 2));
  for (int16_t sample : samples)
    put16(bytes, static_cast<uint16_t>(sample));
  return bytes;
}

void write_fixture(const std::filesystem::path& path,
                   const std::vector<uint8_t>& bytes) {
  std::ofstream dest(path, std::ios::binary | std::ios::trunc);
  assert(dest);
  dest.write(reinterpret_cast<const char*>(bytes.data()),
             static_cast<std::streamsize>(bytes.size()));
  assert(dest.good());
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const auto positive = synthetic(520.f);
  const auto negative = synthetic(900.f);
  const auto wav_positive = canonical_wav(positive);
  const auto wav_negative = canonical_wav(negative);
  assert(parse_wake_pcm24k_wav(wav_positive) == positive);
  assert(parse_wake_pcm24k_wav(wav_negative) == negative);
  assert(!parse_wake_pcm24k_wav(std::span<const uint8_t>(wav_positive).first(43)));
  assert(!parse_wake_pcm24k_wav(std::span<const uint8_t>(wav_positive).first(44)));
  {
    auto malformed = wav_positive;
    malformed[0] = 'X';
    assert(!parse_wake_pcm24k_wav(malformed));
  }
  {
    auto malformed = wav_positive;
    malformed[4] ^= 1; // RIFF size mismatch.
    assert(!parse_wake_pcm24k_wav(malformed));
  }
  {
    auto malformed = wav_positive;
    malformed[20] = 0; // PCM format mismatch.
    assert(!parse_wake_pcm24k_wav(malformed));
  }
  {
    auto malformed = wav_positive;
    malformed[22] = 2; // Stereo not accepted.
    assert(!parse_wake_pcm24k_wav(malformed));
  }
  {
    auto malformed = wav_positive;
    malformed[24] = 0; // Wrong sample clock.
    assert(!parse_wake_pcm24k_wav(malformed));
  }
  {
    auto malformed = wav_positive;
    malformed[40] = 0xff; // Truncated data chunk.
    malformed[41] = 0xff;
    assert(!parse_wake_pcm24k_wav(malformed));
  }
  assert(!parse_wake_pcm24k_wav(canonical_wav(std::vector<int16_t>(2300, 1))));
  assert(!parse_wake_pcm24k_wav(canonical_wav(std::vector<int16_t>(72001, 1))));
  auto feature_positive = wake_mfcc_from_24k(positive);
  auto feature_negative = wake_mfcc_from_24k(negative);
  assert(feature_positive && feature_negative);
  std::array<WakeFeature, 1> templates{*feature_positive};
  std::array<WakeFeature, 5> holds{};
  std::array<WakeFeature, 10> negatives{};
  holds.fill(*feature_positive);
  negatives.fill(*feature_negative);
  auto profile = calibrate_wake(templates, holds, negatives);
  assert(profile && profile->accepts(*feature_positive) &&
         !profile->accepts(*feature_negative));
  auto swk1 = encode_wake_profile(*profile);
  assert(swk1);
  const auto dir = std::filesystem::path(argv[1]);
  write_fixture(dir / "profile.swk1", *swk1);
  write_fixture(dir / "positive.wav", wav_positive);
  write_fixture(dir / "negative.wav", wav_negative);
  write_fixture(dir / "duplicate.wav", wav_positive);
  auto malformed = wav_positive;
  malformed[24] = 0;
  write_fixture(dir / "malformed.wav", malformed);
  std::cout << "canonical WAV parser + synthetic profile fixture PASS\n";
}

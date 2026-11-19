// SPDX-License-Identifier: MIT
// Purely synthetic WAV fixtures: no Korean speech or device capture.
#include "wake_features.hpp"
#include "wake_wav_pcm.hpp"

#include <cassert>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

using namespace stackchan::standalone;

std::vector<int16_t> synth(float hz, float phase, float amplitude) {
  std::vector<int16_t> pcm(24000);
  for (size_t i = 0; i < pcm.size(); ++i) {
    const float t = static_cast<float>(i) / 24000.f;
    const float gate = t < 0.10f || t > 0.9f ? 0.f : 1.f;
    const float value = amplitude * gate *
        (std::sin(2.f*kPi*hz*t + phase) +
         0.34f*std::sin(4.f*kPi*hz*t + phase*0.5f));
    pcm[i] = static_cast<int16_t>(value * 32767.f);
  }
  return pcm;
}
std::vector<uint8_t> make_wav(const std::vector<int16_t>& pcm) {
  std::vector<uint8_t> wav{'R','I','F','F'};
  put32(wav, static_cast<uint32_t>(36 + pcm.size()*2));
  wav.insert(wav.end(), {'W','A','V','E','f','m','t',' '});
  put32(wav, 16); put16(wav, 1); put16(wav, 1);
  put32(wav, 24000); put32(wav, 48000);
  put16(wav, 2); put16(wav, 16);
  wav.insert(wav.end(), {'d','a','t','a'});
  put32(wav, static_cast<uint32_t>(pcm.size()*2));
  for (const auto value : pcm) put16(wav, static_cast<uint16_t>(value));
  return wav;
}
void save(const std::filesystem::path& target, const std::vector<uint8_t>& data) {
  std::ofstream file(target, std::ios::binary);
  assert(file);
  file.write(reinterpret_cast<const char*>(data.data()),
             static_cast<std::streamsize>(data.size()));
  assert(file.good());
}
int main(int argc, char** argv) {
  assert(argc == 2);
  const auto directory = std::filesystem::path(argv[1]);
  const auto enrollment = synth(520.f, 0, 0.30f);
  const auto base = make_wav(enrollment);
  save(directory / "template.wav", base);
  save(directory / "duplicate.wav", base); // different path, same audio.
  auto corrupt = base;
  corrupt[24] = 0; // Wrong sample rate.
  save(directory / "corrupt.wav", corrupt);
  save(directory / "silent.wav", make_wav(std::vector<int16_t>(24000, 0)));

  for (int i = 0; i < 5; ++i) {
    const float delta = static_cast<float>(i + 1) * 0.11f;
    save(directory / ("holdout_" + std::to_string(i) + ".wav"),
         make_wav(synth(520.f + i*0.4f, delta, 0.3f)));
  }
  for (int i = 0; i < 10; ++i) {
    save(directory / ("negative_" + std::to_string(i) + ".wav"),
         make_wav(synth(870.f + i*7.f, i*0.15f, 0.30f)));
  }
  assert(parse_wake_pcm24k_wav(base));
}

// SPDX-License-Identifier: MIT
// Host-only fixed SWK1 single-WAV probe for offline second-stage ASR research.
// No hardware, microphone, paid API, NVS or OTA. No file paths are printed.
// Build with -DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1 only for trim profiles.
#include "offline_wake_feature.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <iostream>
#include <optional>
#include <string_view>
#include <vector>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

using namespace stackchan::standalone;

namespace {
std::optional<std::vector<uint8_t>> read_private_file(
    const char* path, size_t bound) {
  std::error_code ec;
  const auto status = std::filesystem::symlink_status(path, ec);
  if (ec || !std::filesystem::is_regular_file(status) ||
      std::filesystem::is_symlink(status)) return std::nullopt;
  std::ifstream file(path, std::ios::binary | std::ios::ate);
  if (!file) return std::nullopt;
  const std::streamoff length = file.tellg();
  if (length < 1 || length > static_cast<std::streamoff>(bound))
    return std::nullopt;
  std::vector<uint8_t> out(static_cast<size_t>(length));
  file.seekg(0);
  if (!file.read(reinterpret_cast<char*>(out.data()), length))
    return std::nullopt;
  return out;
}
// Exactly one bounded WAV from stdin, for local microphones without a temp file.
// The caller alone owns recording permission and buffering; no audio is logged.
std::optional<std::vector<uint8_t>> read_stdin_wav(size_t bound) {
#if defined(_WIN32)
  if (_setmode(_fileno(stdin), _O_BINARY) == -1) return std::nullopt;
#endif
  std::vector<uint8_t> out;
  std::array<char, 4096> buffer{};
  for (;;) {
    std::cin.read(buffer.data(), buffer.size());
    const auto count = std::cin.gcount();
    if (count < 0 || static_cast<size_t>(count) > bound - out.size())
      return std::nullopt;
    for (std::streamsize i = 0; i < count; ++i)
      out.push_back(static_cast<uint8_t>(buffer[static_cast<size_t>(i)]));
    if (std::cin.eof()) break;
    if (std::cin.bad() || std::cin.fail()) return std::nullopt;
  }
  if (out.empty()) return std::nullopt;
  return out;
}
int refuse() {
  std::cerr << "OFFLINE_WAKE_PROBE_REJECTED\n";
  return 2;
}

std::optional<WakeFeature> feature_from_wav(std::span<const uint8_t> wav) {
  auto pcm = parse_wake_pcm24k_wav(wav);
  if (!pcm) return std::nullopt;
  const auto feature = offline_wake_extract(*pcm);
  std::fill(pcm->begin(), pcm->end(), int16_t{0});
  return feature;
}
int private_pipe(std::string_view mode) {
  constexpr size_t calibration_bytes = 18 * kWakeBytes;
  auto bytes = read_stdin_wav(mode == "--calibrate" ? calibration_bytes :
      kWakeWavMaxFileBytes + 2509);
  if (!bytes) return refuse();
  // Every input is bounded. Never echo raw audio/features in diagnostic modes.
  if (mode == "--features") {
    if (bytes->size() > kWakeWavMaxFileBytes) return refuse();
    auto feature = feature_from_wav(*bytes);
    std::fill(bytes->begin(), bytes->end(), uint8_t{0});
    if (!feature) return refuse();
#if defined(_WIN32)
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) return refuse();
#endif
    std::cout.write(reinterpret_cast<const char*>(feature->quantized.data()), kWakeBytes);
    std::fill(feature->quantized.begin(), feature->quantized.end(), int8_t{0});
    return std::cout.good() ? 0 : refuse();
  }
  if (mode == "--calibrate") {
    if (bytes->size() != calibration_bytes) return refuse();
    std::array<WakeFeature, 18> features{};
    for (size_t n = 0; n < features.size(); ++n) {
      for (size_t i = 0; i < kWakeBytes; ++i)
        features[n].quantized[i] = static_cast<int8_t>((*bytes)[n*kWakeBytes+i]);
      for (size_t previous = 0; previous < n; ++previous)
        if (features[n] == features[previous]) return refuse();
    }
    std::fill(bytes->begin(), bytes->end(), uint8_t{0});
    auto profile = calibrate_wake(std::span(features).first(3),
        std::span(features).subspan(3,5), std::span(features).subspan(8,10));
    for (auto &feature : features) feature.quantized.fill(0);
    if (!profile) return refuse();
    auto wire = encode_wake_profile(*profile);
    if (!wire) return refuse();
#if defined(_WIN32)
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) return refuse();
#endif
    std::cout.write(reinterpret_cast<const char*>(wire->data()), wire->size());
    std::fill(wire->begin(), wire->end(), uint8_t{0});
    return std::cout.good() ? 0 : refuse();
  }
  if (bytes->size() < 2) return refuse();
  const size_t profile_size = size_t((*bytes)[0])*256 + (*bytes)[1];
  if (profile_size < 843 || profile_size > 2507 || bytes->size() <= 2+profile_size)
    return refuse();
  auto all = std::span<const uint8_t>(*bytes);
  auto profile = decode_wake_profile(all.subspan(2,profile_size));
  auto feature = feature_from_wav(all.subspan(2+profile_size));
  std::fill(bytes->begin(), bytes->end(), uint8_t{0});
  if (!profile || !feature) return refuse();
  float best = std::numeric_limits<float>::infinity();
  for (const auto &sample : profile->templates)
    best = std::min(best, wake_dtw_distance(sample,*feature)*256.f);
  std::cout << "{\"accepted\":" << (profile->accepts(*feature) ? "true" : "false")
      << ",\"distance_q8\":" << std::setprecision(9) << best
      << ",\"limit_q8\":" << profile->limit_q8 << "}\n";
  return std::cout.good() ? 0 : refuse();
}
} // namespace

int main(int argc, char** argv) {
  if (argc != 3) return refuse();
  const std::string_view mode(argv[1]);
  if ((mode == "--features" || mode == "--calibrate" || mode == "--score") &&
      std::string_view(argv[2]) == "-") return private_pipe(mode);
  auto raw_profile = read_private_file(argv[1], 2507);
  if (!raw_profile) return refuse();
  const auto profile = decode_wake_profile(*raw_profile);
  std::fill(raw_profile->begin(), raw_profile->end(), uint8_t{0});
  if (!profile) return refuse();

  auto wav = std::string_view(argv[2]) == "-" ?
      read_stdin_wav(kWakeWavMaxFileBytes) :
      read_private_file(argv[2], kWakeWavMaxFileBytes);
  if (!wav) return refuse();
  auto pcm = parse_wake_pcm24k_wav(*wav);
  std::fill(wav->begin(), wav->end(), uint8_t{0});
  if (!pcm) return refuse();
  const auto feature = offline_wake_extract(*pcm);
  std::fill(pcm->begin(), pcm->end(), int16_t{0});
  if (!feature) return refuse();

  std::cout << (profile->accepts(*feature) ?
      "OFFLINE_STAGE1_ACCEPT\n" : "OFFLINE_STAGE1_REJECT\n");
  return 0;
}

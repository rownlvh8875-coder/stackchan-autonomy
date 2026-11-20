// SPDX-License-Identifier: MIT
// Host-only fixed SWK1 single-WAV probe for offline second-stage ASR research.
// No hardware, microphone, paid API, NVS or OTA. No file paths are printed.
// Build with -DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1 only for trim profiles.
#include "offline_wake_feature.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <vector>

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
int refuse() {
  std::cerr << "OFFLINE_WAKE_PROBE_REJECTED\n";
  return 2;
}
} // namespace

int main(int argc, char** argv) {
  if (argc != 3) return refuse();
  auto raw_profile = read_private_file(argv[1], 2507);
  if (!raw_profile) return refuse();
  const auto profile = decode_wake_profile(*raw_profile);
  std::fill(raw_profile->begin(), raw_profile->end(), uint8_t{0});
  if (!profile) return refuse();

  auto wav = read_private_file(argv[2], kWakeWavMaxFileBytes);
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

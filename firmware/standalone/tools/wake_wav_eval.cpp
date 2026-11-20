// SPDX-License-Identifier: MIT
// PRIVATE WAV samples vs PRIVATE SWK1 profile, offline. NO networking or writes.
// Labels are supplied by the user, NOT inferred from audio content.
#include "offline_wake_feature.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;

namespace {
std::optional<std::vector<uint8_t>> read_private_file(
    const char* path, size_t bound) {
  std::error_code ec;
  const auto state = std::filesystem::symlink_status(path, ec);
  if (ec || !std::filesystem::is_regular_file(state) ||
      std::filesystem::is_symlink(state)) return std::nullopt;
  std::ifstream source(path, std::ios::binary | std::ios::ate);
  if (!source) return std::nullopt;
  const std::streamoff length = source.tellg();
  if (length < 0 || length > static_cast<std::streamoff>(bound))
    return std::nullopt;
  std::vector<uint8_t> bytes(static_cast<size_t>(length));
  source.seekg(0, std::ios::beg);
  if (length > 0 &&
      !source.read(reinterpret_cast<char*>(bytes.data()), length))
    return std::nullopt;
  return bytes;
}
int refuse() {
  // Never print paths, waveforms, profile features or owner identifiers.
  std::cerr << "REJECTED_OFFLINE_WAKE_EVALUATION; no device or API accessed\n";
  return 2;
}
} // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string_view(argv[1]) == "--help") {
    std::cout << "Usage: wake_wav_eval PRIVATE.swk1 "
                 "--positive PRIVATE_24k_mono.wav "
                 "--negative PRIVATE_24k_mono.wav [more labeled samples]\n"
                 "OFFLINE / UNVERIFIED / NO DEVICE / NO API / NO FILE WRITES\n";
    return 0;
  }
  if (argc < 6 || argc > 104 || ((argc - 2) % 2 != 0)) return refuse();
  auto raw_profile = read_private_file(argv[1], 2507);
  if (!raw_profile) return refuse();
  auto profile = decode_wake_profile(*raw_profile);
  std::fill(raw_profile->begin(), raw_profile->end(), uint8_t{0});
  if (!profile) return refuse();

  unsigned positive_total = 0, positive_accepts = 0;
  unsigned negative_total = 0, negative_accepts = 0;
  std::vector<std::vector<int16_t>> distinct_pcm;
  for (int index = 2; index < argc; index += 2) {
    const std::string_view label(argv[index]);
    if (label != "--positive" && label != "--negative") return refuse();
    const bool positive = label == "--positive";
    auto raw = read_private_file(argv[index + 1], kWakeWavMaxFileBytes);
    if (!raw) return refuse();
    auto samples = parse_wake_pcm24k_wav(*raw);
    std::fill(raw->begin(), raw->end(), uint8_t{0});
    if (!samples) return refuse();

    // Duplicate PCM samples cannot be counted as independent evidence,
    // even when file names or RIFF metadata are changed.
    for (const auto& prior : distinct_pcm)
      if (prior == *samples) return refuse();

    const auto feature = offline_wake_extract(*samples);
    if (!feature) return refuse(); // Silence is not a valid ground-truth trial.
    const bool accepted = profile->accepts(*feature);
    if (positive) {
      ++positive_total;
      if (accepted) ++positive_accepts;
    } else {
      ++negative_total;
      if (accepted) ++negative_accepts;
    }
    distinct_pcm.push_back(std::move(*samples));
  }
  if (positive_total == 0 || negative_total == 0) return refuse();

  std::cout << "UNVERIFIED_USER_LABELED_WAKE_EVALUATION\n"
            << "positive_accepted=" << positive_accepts << "/" << positive_total << "\n"
            << "negative_accepted=" << negative_accepts << "/" << negative_total << "\n"
            << "Independent utterances, labels, acoustic quality and hardware "
               "wake accuracy NOT verified. NO device/API/install approval.\n";
  return 0;
}

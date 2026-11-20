// SPDX-License-Identifier: MIT
// Host-only negative-calibration contrastive wake test, not K151 firmware.
// Usage: evaluator PRIVATE.swk1 --calibration-negative ... (10..48)
//                  --positive ... --negative ...  (at least one each)
// Only aggregate counts; no paths/voice/profile data printed or uploaded.
#include "offline_contrastive_wake.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <cstdint>
#include <cmath>
#include <limits>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <span>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;

namespace {
std::optional<std::vector<uint8_t>> read_private_file(
    const char* path, size_t max_bytes) {
  std::error_code error;
  const auto status = std::filesystem::symlink_status(path, error);
  if (error || !std::filesystem::is_regular_file(status) ||
      std::filesystem::is_symlink(status)) return std::nullopt;
  std::ifstream stream(path, std::ios::binary | std::ios::ate);
  if (!stream) return std::nullopt;
  const std::streamoff size = stream.tellg();
  if (size < 0 || size > static_cast<std::streamoff>(max_bytes))
    return std::nullopt;
  std::vector<uint8_t> result(static_cast<size_t>(size));
  stream.seekg(0, std::ios::beg);
  if (size > 0 && !stream.read(reinterpret_cast<char*>(result.data()), size))
    return std::nullopt;
  return result;
}
int fail_closed() {
  std::cerr << "REJECTED_OFFLINE_CONTRASTIVE_TEST; no API/device accessed\n";
  return 2;
}
} // namespace

int main(int argc, char** argv) {
  if (argc < 26 || argc > 210 || (argc - 2) % 2 != 0)
    return fail_closed();
  auto raw_profile = read_private_file(argv[1], 2507);
  if (!raw_profile) return fail_closed();
  auto positive = decode_wake_profile(*raw_profile);
  std::fill(raw_profile->begin(), raw_profile->end(), uint8_t{0});
  if (!positive) return fail_closed();

  std::vector<WakeFeature> negative_features;
  std::vector<std::vector<int16_t>> seen_pcm;
  std::vector<std::pair<bool, WakeFeature>> probes;
  unsigned positive_total = 0, negative_total = 0;
  for (int i=2; i<argc; i+=2) {
    const std::string_view flag(argv[i]);
    const bool calibration = flag == "--calibration-negative";
    const bool is_positive = flag == "--positive";
    const bool is_negative = flag == "--negative";
    if (!calibration && !is_positive && !is_negative)
      return fail_closed();
    auto wav = read_private_file(argv[i+1], kWakeWavMaxFileBytes);
    if (!wav) return fail_closed();
    auto pcm = parse_wake_pcm24k_wav(*wav);
    std::fill(wav->begin(), wav->end(), uint8_t{0});
    if (!pcm) return fail_closed();
    for (const auto& earlier : seen_pcm)
      if (earlier == *pcm) return fail_closed();
    auto feature = offline_wake_extract(*pcm);
    if (!feature) return fail_closed();
    if (calibration) {
      if (negative_features.size() >= kContrastiveMaxNegatives)
        return fail_closed();
      negative_features.push_back(*feature);
    } else {
      probes.emplace_back(is_positive, *feature);
      if (is_positive) ++positive_total;
      else ++negative_total;
    }
    seen_pcm.push_back(std::move(*pcm));
  }
  if (negative_features.size() < 10 || positive_total == 0 ||
      negative_total == 0) return fail_closed();

  unsigned positive_accepted=0, negative_accepted=0;
  float min_wake_margin = std::numeric_limits<float>::infinity();
  float max_wrong_margin = 0.f;
  for (const auto& [labeled_wake, feature] : probes) {
    const auto result = offline_contrastive_wake(*positive, negative_features, feature);
    if (!result) return fail_closed();
    if (positive->accepts(feature)) {
      // Diagnostic based on the DEVELOPMENT ONLY probes. Never expose
      // speech content, embeddings, utterance filenames or individual scores.
      const float ratio = result->nearest_nonwake_distance /
          std::max(result->best_wake_distance, 1.e-6f);
      if (!std::isfinite(ratio)) return fail_closed();
      if (labeled_wake) min_wake_margin = std::min(min_wake_margin, ratio);
      else max_wrong_margin = std::max(max_wrong_margin, ratio);
    }
    if (result->accepted) {
      if (labeled_wake) ++positive_accepted;
      else ++negative_accepted;
    }
  }
  std::cout << "UNVERIFIED_CALIBRATION_ONLY_CONTRASTIVE_WAKE\n"
            << "calibration_negative_count=" << negative_features.size() << "\n"
            << "positive_accepted=" << positive_accepted << "/" << positive_total << "\n"
            << "negative_accepted=" << negative_accepted << "/" << negative_total << "\n"
            << "min_wake_margin_ratio_x1000=" <<
                (std::isfinite(min_wake_margin) ? static_cast<int>(std::min(min_wake_margin*1000.f, 1000000.f)) : -1) << "\n"
            << "max_false_wake_margin_ratio_x1000=" <<
                static_cast<int>(std::min(max_wrong_margin*1000.f, 1000000.f)) << "\n"
            << "Developer rule: nearest nonwake distance > nearest wake distance"
               " * 2.0 and positive SWK1 threshold. No K151 installation approval.\n";
  return 0;
}

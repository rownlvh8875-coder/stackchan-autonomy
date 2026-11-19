// SPDX-License-Identifier: MIT
// Offline private WAV -> calibrated SWK1 profile. Never contacts a device/API.
// Labels and recording independence are operator-supplied, NOT proven here.
#include "wake_features.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <span>
#include <string_view>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

using namespace stackchan::standalone;

namespace {
constexpr size_t kMaxTemplates = 3;
constexpr size_t kMaxHoldouts = 32;
constexpr size_t kMaxNegatives = 64;
constexpr size_t kMaxInputPairs = kMaxTemplates + kMaxHoldouts + kMaxNegatives + 1;

struct PrivatePcm {
  std::vector<std::vector<int16_t>> distinct;
  ~PrivatePcm() {
    // Best effort. This is not a cryptographic guarantee of RAM erasure.
    for (auto& pcm : distinct) std::fill(pcm.begin(), pcm.end(), 0);
  }
};

int refuse() {
  // No owner identifiers, feature values, file paths or audio in output.
  std::cerr << "REJECTED_PRIVATE_WAKE_ENROLLMENT; no device/API accessed\n";
  return 2;
}

std::optional<std::vector<uint8_t>> read_private_wav(const char* path) {
  std::error_code ec;
  const auto status = std::filesystem::symlink_status(path, ec);
  if (ec || std::filesystem::is_symlink(status) ||
      !std::filesystem::is_regular_file(status)) return std::nullopt;
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) return std::nullopt;
  const std::streamoff length = input.tellg();
  if (length < 44 ||
      length > static_cast<std::streamoff>(kWakeWavMaxFileBytes))
    return std::nullopt;
  std::vector<uint8_t> data(static_cast<size_t>(length));
  input.seekg(0);
  if (!input.read(reinterpret_cast<char*>(data.data()), length))
    return std::nullopt;
  return data;
}

bool save_new_private_profile(const char* path, std::span<const uint8_t> bytes) {
  // Exclusive creation: never overwrite an existing file or symlink.
#ifdef _WIN32
  const int fd = _open(path, _O_WRONLY | _O_BINARY | _O_CREAT | _O_EXCL |
                            _O_NOINHERIT, _S_IREAD | _S_IWRITE);
#else
  const int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC |
                             O_NOFOLLOW, 0600);
#endif
  if (fd < 0) return false;
  size_t sent = 0;
  bool okay = true;
  while (sent < bytes.size()) {
    const size_t remaining = bytes.size() - sent;
#ifdef _WIN32
    const int n = _write(fd, bytes.data() + sent,
                         static_cast<unsigned>(remaining));
#else
    const ssize_t n = write(fd, bytes.data() + sent, remaining);
#endif
    if (n <= 0) { okay = false; break; }
    sent += static_cast<size_t>(n);
  }
#ifdef _WIN32
  if (_close(fd) != 0) okay = false;
  if (!okay) (void)_unlink(path);
#else
  if (close(fd) != 0) okay = false;
  if (!okay) (void)unlink(path);
#endif
  return okay && sent == bytes.size();
}
} // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string_view(argv[1]) == "--help") {
    std::cout << "Usage: wake_wav_enroll --template PRIVATE.wav "
                 "[--template PRIVATE.wav] --holdout PRIVATE.wav (5+) "
                 "--negative PRIVATE.wav (10+) --output NEW_PRIVATE.swk1\n"
                 "24kHz mono PCM16 WAV only; offline, no device/API. "
                 "No overwrite. Do not commit private voice/profile files.\n";
    return 0;
  }
  if (argc < 3 || (argc - 1) % 2 != 0 ||
      (argc - 1) / 2 > static_cast<int>(kMaxInputPairs)) return refuse();

  std::vector<WakeFeature> templates, holdouts, negatives;
  PrivatePcm recorded;
  const char* output_path = nullptr;
  for (int i = 1; i < argc; i += 2) {
    const std::string_view flag(argv[i]);
    if (flag == "--output") {
      if (output_path != nullptr || argv[i + 1][0] == '\0') return refuse();
      output_path = argv[i + 1];
      continue;
    }
    std::vector<WakeFeature>* target = nullptr;
    size_t max_count = 0;
    if (flag == "--template") {
      target = &templates;
      max_count = kMaxTemplates;
    } else if (flag == "--holdout") {
      target = &holdouts;
      max_count = kMaxHoldouts;
    } else if (flag == "--negative") {
      target = &negatives;
      max_count = kMaxNegatives;
    } else {
      return refuse();
    }
    if (target->size() >= max_count) return refuse();
    auto wav = read_private_wav(argv[i + 1]);
    if (!wav) return refuse();
    auto pcm = parse_wake_pcm24k_wav(*wav);
    std::fill(wav->begin(), wav->end(), uint8_t{0});
    if (!pcm) return refuse();
    for (const auto& prior : recorded.distinct)
      if (prior == *pcm) return refuse(); // metadata changes do not help.
    const auto feature = wake_mfcc_from_24k(*pcm);
    if (!feature) return refuse(); // includes silence or invalid energy.
    recorded.distinct.push_back(std::move(*pcm));
    target->push_back(*feature);
  }
  if (output_path == nullptr || templates.empty() ||
      holdouts.size() < 5 || negatives.size() < 10) return refuse();

  const auto profile = calibrate_wake(templates, holdouts, negatives);
  if (!profile) return refuse();
  // A quantized SWK1 threshold must preserve separation; no rounding pass.
  for (const auto& positive : holdouts)
    if (!profile->accepts(positive)) return refuse();
  for (const auto& negative : negatives)
    if (profile->accepts(negative)) return refuse();
  const auto wire = encode_wake_profile(*profile);
  if (!wire || !decode_wake_profile(*wire)) return refuse();
  if (!save_new_private_profile(output_path, *wire)) return refuse();

  std::cout << "UNVERIFIED_PRIVATE_WAKE_PROFILE_WRITTEN\n"
            << "template_count=" << templates.size()
            << " holdout_count=" << holdouts.size()
            << " negative_count=" << negatives.size() << "\n"
            << "Training/holdout independence and Korean wake recognition "
               "accuracy NOT established. NO device/API/install approval.\n";
  return 0;
}

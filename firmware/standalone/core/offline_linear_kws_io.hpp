// SPDX-License-Identifier: MIT
// Offline research-only file utilities. No device access, network or APIs.
// Manifest lines: W<TAB>absolute-or-relative-file.wav or N<TAB>... .
#pragma once
#include "offline_linear_kws.hpp"
#include "wake_wav_pcm.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <set>
#include <span>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace stackchan::standalone {

struct OfflineLabeledPath {
  bool wake = false;
  std::string path;
};

inline std::optional<std::vector<uint8_t>> offline_read_file(
    const std::filesystem::path& file, size_t limit) {
  std::error_code error;
  const auto status = std::filesystem::symlink_status(file, error);
  if (error || !std::filesystem::is_regular_file(status) ||
      std::filesystem::is_symlink(status)) return std::nullopt;
  std::ifstream stream(file, std::ios::binary | std::ios::ate);
  if (!stream) return std::nullopt;
  const std::streamoff size = stream.tellg();
  if (size <= 0 || size > static_cast<std::streamoff>(limit))
    return std::nullopt;
  std::vector<uint8_t> result(static_cast<size_t>(size));
  stream.seekg(0);
  if (!stream.read(reinterpret_cast<char*>(result.data()), size))
    return std::nullopt;
  return result;
}

inline std::optional<std::vector<OfflineLabeledPath>> offline_labeled_manifest(
    const std::filesystem::path& filename) {
  const auto bytes = offline_read_file(filename, 65536);
  if (!bytes) return std::nullopt;
  const std::string raw(bytes->begin(), bytes->end());
  std::vector<OfflineLabeledPath> rows;
  std::set<std::string> unique_paths;
  size_t position = 0;
  while (position < raw.size()) {
    const auto next = raw.find('\n', position);
    const size_t end = next == std::string::npos ? raw.size() : next;
    std::string line = raw.substr(position, end-position);
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.size() < 4 || line.size() > 600 ||
        (line[0] != 'W' && line[0] != 'N') || line[1] != '\t')
      return std::nullopt;
    const auto path = line.substr(2);
    if (path.empty() || path.find('\0') != std::string::npos ||
        !unique_paths.insert(path).second)
      return std::nullopt;
    rows.push_back({line[0] == 'W', path});
    if (rows.size() > kLinearKwsMaxTrainingExamples)
      return std::nullopt;
    position = next == std::string::npos ? raw.size() : next+1;
  }
  if (rows.empty()) return std::nullopt;
  return rows;
}

inline uint64_t offline_pcm_fingerprint(std::span<const int16_t> pcm) {
  // Conservative duplicate screening; FNV-1a collision also rejects an
  // example rather than incorrectly granting independent training evidence.
  uint64_t hash = 14695981039346656037ULL;
  for (const auto item : pcm) {
    const uint16_t word = static_cast<uint16_t>(item);
    for (const uint8_t byte : {
        static_cast<uint8_t>(word), static_cast<uint8_t>(word >> 8)}) {
      hash ^= byte;
      hash *= 1099511628211ULL;
    }
  }
  hash ^= pcm.size();
  return hash;
}

inline std::optional<LinearKwsVector> offline_labeled_feature(
    const std::filesystem::path& file, uint64_t& fingerprint) {
  auto bytes = offline_read_file(file, kWakeWavMaxFileBytes);
  if (!bytes) return std::nullopt;
  auto pcm = parse_wake_pcm24k_wav(*bytes);
  std::fill(bytes->begin(), bytes->end(), uint8_t{0});
  if (!pcm) return std::nullopt;
  fingerprint = offline_pcm_fingerprint(*pcm);
  const auto features = wake_mfcc_from_24k(*pcm);
  std::fill(pcm->begin(), pcm->end(), int16_t{0});
  if (!features) return std::nullopt;
  return linear_kws_pool(*features);
}

inline bool offline_write_exclusive(
    const char* filename, std::span<const uint8_t> binary) {
#ifdef _WIN32
  const int fd = _open(filename,
      _O_BINARY | _O_WRONLY | _O_CREAT | _O_EXCL | _O_NOINHERIT,
      _S_IREAD | _S_IWRITE);
#else
  const int fd = open(filename,
      O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
#endif
  if (fd < 0) return false;
  size_t done = 0;
  bool ok = true;
  while (done < binary.size()) {
#ifdef _WIN32
    const int n = _write(fd, binary.data()+done,
        static_cast<unsigned>(binary.size()-done));
#else
    const ssize_t n = write(fd, binary.data()+done, binary.size()-done);
#endif
    if (n <= 0) { ok = false; break; }
    done += static_cast<size_t>(n);
  }
#ifdef _WIN32
  if (_close(fd) != 0) ok = false;
  if (!ok) (void)_unlink(filename);
#else
  if (close(fd) != 0) ok = false;
  if (!ok) (void)unlink(filename);
#endif
  return ok && done == binary.size();
}

} // namespace stackchan::standalone

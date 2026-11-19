// SPDX-License-Identifier: MIT
// Canonical RIFF/WAVE 24kHz mono PCM16 parser. Pure, bounded and host-testable.
// Metadata is not echoed. Unsupported/malformed audio fails closed.
#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {
inline constexpr size_t kWakeWavMaxFileBytes = 196608;
inline constexpr size_t kWakeWavMinSamples = 2400;  // 100ms
inline constexpr size_t kWakeWavMaxSamples = 72000; // 3 seconds

inline uint16_t wav16(std::span<const uint8_t> b, size_t pos) {
  return static_cast<uint16_t>(b[pos]) |
         (static_cast<uint16_t>(b[pos + 1]) << 8U);
}
inline uint32_t wav32(std::span<const uint8_t> b, size_t pos) {
  return static_cast<uint32_t>(wav16(b, pos)) |
         (static_cast<uint32_t>(wav16(b, pos + 2)) << 16U);
}
inline bool wav_tag(std::span<const uint8_t> b, size_t pos,
                    char a, char c, char d, char e) {
  return b[pos] == static_cast<uint8_t>(a) &&
         b[pos + 1] == static_cast<uint8_t>(c) &&
         b[pos + 2] == static_cast<uint8_t>(d) &&
         b[pos + 3] == static_cast<uint8_t>(e);
}

inline std::optional<std::vector<int16_t>> parse_wake_pcm24k_wav(
    std::span<const uint8_t> bytes) {
  if (bytes.size() < 44 || bytes.size() > kWakeWavMaxFileBytes ||
      !wav_tag(bytes, 0, 'R','I','F','F') ||
      !wav_tag(bytes, 8, 'W','A','V','E') ||
      wav32(bytes, 4) != bytes.size() - 8)
    return std::nullopt;

  bool has_fmt = false, has_data = false;
  size_t pos = 12;
  std::vector<int16_t> samples;
  while (pos < bytes.size()) {
    if (bytes.size() - pos < 8) return std::nullopt;
    const size_t chunk_size = wav32(bytes, pos + 4);
    const size_t body = pos + 8;
    if (chunk_size > bytes.size() - body) return std::nullopt;
    if (wav_tag(bytes, pos, 'f','m','t',' ')) {
      if (has_fmt || has_data || chunk_size != 16 ||
          wav16(bytes, body) != 1 ||           // Integer PCM
          wav16(bytes, body + 2) != 1 ||       // mono
          wav32(bytes, body + 4) != 24000 ||
          wav32(bytes, body + 8) != 48000 ||  // Byte rate
          wav16(bytes, body + 12) != 2 ||     // Block align
          wav16(bytes, body + 14) != 16)      // PCM16
        return std::nullopt;
      has_fmt = true;
    } else if (wav_tag(bytes, pos, 'd','a','t','a')) {
      if (!has_fmt || has_data || chunk_size % 2 != 0 ||
          chunk_size / 2 < kWakeWavMinSamples ||
          chunk_size / 2 > kWakeWavMaxSamples)
        return std::nullopt;
      has_data = true;
      samples.reserve(chunk_size / 2);
      for (size_t i = 0; i < chunk_size; i += 2) {
        const uint16_t word = wav16(bytes, body + i);
        const int32_t signed_sample =
            word < 32768U ? static_cast<int32_t>(word) :
                            static_cast<int32_t>(word) - 65536;
        samples.push_back(static_cast<int16_t>(signed_sample));
      }
    }
    pos = body + chunk_size;
    if (chunk_size & 1U) {
      if (pos == bytes.size()) return std::nullopt;
      ++pos; // RIFF chunk padding.
    }
  }
  if (pos != bytes.size() || !has_fmt || !has_data)
    return std::nullopt;
  return samples;
}
} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
// Bounded JSON schema and raw-PCM decoding; dormant until device approval.
#pragma once
#include <cstdint>
#include <span>
#include <string>
#include <vector>
namespace stackchan::standalone {
class K151VoiceDecoder final {
 public:
  static const char* compiled_link_marker();
  static bool transcription(std::span<const uint8_t> json, std::string& text);
  static bool response_text(std::span<const uint8_t> json, std::string& text);
  static bool speech_pcm(std::span<const uint8_t> bytes, std::vector<int16_t>& pcm);
};
}  // namespace stackchan::standalone

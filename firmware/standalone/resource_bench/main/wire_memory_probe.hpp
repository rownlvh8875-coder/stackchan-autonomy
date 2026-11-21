// SPDX-License-Identifier: MIT
#pragma once

#include "k151_voice_decode.hpp"
#include "openai_http_wire.hpp"

namespace stackchan::standalone {

// Synthetic, socket-free exercise of the same receiver and decoder used by
// the HTTPS path. The caller retains the question and model for the whole run.
template<class Allowed, class Observe>
bool probe_wire_memory(std::vector<int16_t>& decoded_pcm, Allowed allowed, Observe observe) {
  using namespace httpwire;
  if (!allowed() || !decoded_pcm.empty()) return false;
  {
    BoundedReply response(Endpoint::responses);
    constexpr std::string_view prefix =
        R"({"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"test"}]}],"padding":")";
    constexpr std::string_view suffix = "\"}";
    const auto bytes = [](std::string_view s) {
      return std::span(reinterpret_cast<const uint8_t*>(s.data()), s.size());
    };
    if (!response.begin(200, "application/json", kMaxJsonBytes, false) ||
        !response.append(bytes(prefix))) return false;
    std::array<uint8_t, 1024> padding;
    padding.fill('x');
    size_t remaining = kMaxJsonBytes - prefix.size() - suffix.size();
    while (remaining != 0) {
      const size_t count = std::min(remaining, padding.size());
      if (!allowed() || !response.append(std::span{padding}.first(count))) return false;
      remaining -= count;
    }
    if (!allowed() || !response.append(bytes(suffix)) || !response.finish(true)) return false;
    auto raw = response.take_bytes();
    std::string answer;
    if (!allowed() || !K151VoiceDecoder::response_text(raw, answer) || answer != "test" ||
        !allowed() || !observe(Endpoint::responses, raw, decoded_pcm)) return false;
  }

  BoundedReply response(Endpoint::speech);
  if (!allowed() || !response.begin(200, "audio/pcm", std::nullopt, true)) return false;
  const std::array<uint8_t, 1024> silence{};
  for (size_t offset = 0; offset < kMaxSpeechBytes; offset += silence.size()) {
    if (!allowed() || !response.append(std::span{silence}.first(
        std::min(silence.size(), kMaxSpeechBytes - offset)))) return false;
  }
  if (!allowed() || !response.finish(true)) return false;
  auto raw = response.take_bytes();
  return allowed() && K151VoiceDecoder::speech_pcm(raw, decoded_pcm) &&
         decoded_pcm.size() == OfflineVoiceCycle::kMaxSynthFrames &&
         allowed() && observe(Endpoint::speech, raw, decoded_pcm) && allowed();
}

} // namespace stackchan::standalone

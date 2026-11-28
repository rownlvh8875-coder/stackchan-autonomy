// SPDX-License-Identifier: MIT
// Bounded JSON schema and raw-PCM decoding; dormant until device approval.
#pragma once
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>
namespace stackchan::standalone {
class K151VoiceDecoder final {
 public:
  static const char* compiled_link_marker();
  static bool transcription(std::span<const uint8_t> json, std::string& text);
  static bool response_text(std::span<const uint8_t> json, std::string& text);
  static bool speech_pcm(std::span<const uint8_t> bytes, std::vector<int16_t>& pcm);
};

// Single Realtime synthesis response. The transport supplies whole UTF-8 text
// messages on the same task. PCM is released only after both terminal events.
class K151RealtimeSpeechExchange final {
 public:
  static constexpr std::size_t kMaxEventBytes = 32 * 1024;
  enum class State { connecting, ready, waiting_response, audio, audio_done, complete, failed };

  K151RealtimeSpeechExchange() = default;
  ~K151RealtimeSpeechExchange();
  K151RealtimeSpeechExchange(const K151RealtimeSpeechExchange&) = delete;
  K151RealtimeSpeechExchange& operator=(const K151RealtimeSpeechExchange&) = delete;

  static std::optional<std::string> response_request(std::string_view voice,
                                                     std::string_view answer);
  bool begin_response();
  bool accept(std::span<const uint8_t> message);
  State state() const { return state_; }
  std::vector<uint8_t> take_pcm();

 private:
  bool fail();
  State state_ = State::connecting;
  bool conversation_created_ = false;
  bool session_pcm24k_ = false;
  std::string response_id_;
  std::string item_id_;
  std::vector<uint8_t> pcm_;
};
}  // namespace stackchan::standalone

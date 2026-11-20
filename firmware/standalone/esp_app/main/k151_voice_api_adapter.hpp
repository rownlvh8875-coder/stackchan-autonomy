// SPDX-License-Identifier: MIT
// Compile-only ESP32-S3 binding. The HOLD entrypoint does not construct this.
#pragma once
#include "voice_api_bridge.hpp"
#include "k151_https_voice.hpp"
#include "k151_wifi_time.hpp"
#include "k151_voice_decode.hpp"
#include <atomic>
#include <cstdint>
#include <string_view>

namespace stackchan::standalone {

// TLS client uses a fresh zeroized per-request API key snapshot from
// K151WifiTimePort. It never holds an unowned string_view between requests.
class K151HttpChannel final : public VoiceHttpChannel {
 public:
  K151HttpChannel(const K151WifiTimePort& network,
                  const std::atomic_bool& owner_consent,
                  const std::atomic_bool& physical_stop)
      : network_(network), consent_(owner_consent), stop_(physical_stop) {}
  static const char* compiled_link_marker();
  bool post_once(const VoiceApiRequest& request,
                 const std::function<bool()>& spend_dispatch,
                 std::vector<uint8_t>& body,
                 uint64_t& completed_ms) override;
 private:
  const K151WifiTimePort& network_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& stop_;
  K151HttpsVoicePort http_;
};

class K151ReplyCodec final : public VoiceReplyCodec {
 public:
  bool transcription(std::span<const uint8_t> bytes, std::string& out) override {
    return K151VoiceDecoder::transcription(bytes, out);
  }
  bool response_text(std::span<const uint8_t> bytes, std::string& out) override {
    return K151VoiceDecoder::response_text(bytes, out);
  }
  bool speech_pcm(std::span<const uint8_t> bytes,
                  std::vector<int16_t>& out) override {
    return K151VoiceDecoder::speech_pcm(bytes, out);
  }
};

// A future owner-controlled runtime may construct a single session-scoped
// instance. No device startup path or model configuration is supplied here.
class K151VoiceApiAdapter final {
 public:
  K151VoiceApiAdapter(const K151WifiTimePort& network,
                      const std::atomic_bool& consent,
                      const std::atomic_bool& stop);
  static const char* compiled_link_marker();
  VoiceApiPort& api() { return binding_; }
 private:
  K151HttpChannel http_;
  K151ReplyCodec codec_;
  BoundVoiceApiPort binding_;
};
} // namespace stackchan::standalone

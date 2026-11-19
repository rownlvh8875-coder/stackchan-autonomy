// SPDX-License-Identifier: MIT
// Compile-only ESP32-S3 binding. The HOLD entrypoint does not construct this.
#pragma once
#include "voice_api_bridge.hpp"
#include "k151_https_voice.hpp"
#include "k151_voice_decode.hpp"
#include <atomic>
#include <cstdint>
#include <string_view>

namespace stackchan::standalone {

// Owner of the fixed-host TLS client. The API key's storage belongs to the
// future approved configuration controller and MUST outlive this object.
class K151HttpChannel final : public VoiceHttpChannel {
 public:
  K151HttpChannel(std::string_view api_key,
                  const std::atomic_bool& wifi,
                  const std::atomic_bool& trusted_clock,
                  const std::atomic_bool& owner_consent,
                  const std::atomic_bool& physical_stop)
      : key_(api_key), wifi_(wifi), trusted_(trusted_clock),
        consent_(owner_consent), stop_(physical_stop) {}
  static const char* compiled_link_marker();
  bool post_once(const VoiceApiRequest& request,
                 const std::function<bool()>& spend_dispatch,
                 std::vector<uint8_t>& body,
                 uint64_t& completed_ms) override;
 private:
  std::string_view key_;
  const std::atomic_bool& wifi_;
  const std::atomic_bool& trusted_;
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
  K151VoiceApiAdapter(std::string_view key, const std::atomic_bool& wifi,
                      const std::atomic_bool& trusted,
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

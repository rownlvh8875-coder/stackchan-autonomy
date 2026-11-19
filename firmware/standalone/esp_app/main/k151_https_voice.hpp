// SPDX-License-Identifier: MIT
// Gated HTTPS adapter. NOT constructed or invoked by HOLD app_main.
#pragma once
#include "openai_http_wire.hpp"
#include <atomic>
#include <cstdint>
#include <functional>
#include <span>
#include <string_view>
#include <vector>
namespace stackchan::standalone {
class K151HttpsVoicePort final {
 public:
  static const char* compiled_link_marker();
  struct Request {
    httpwire::Endpoint endpoint;
    std::string_view model, voice, text;
    std::span<const int16_t> pcm24k;
  };
  struct Reply {
    std::vector<uint8_t> body;
    uint64_t received_ms=0;
  };
  // The caller MUST supply a durable one-shot stage-permit callback.
  // No call exists in app_main. Wi-Fi/SNTP/owner consent are prerequisites.
  bool post_once(const Request& request, std::string_view key,
                 bool wifi_ready, bool trusted_sntp,
                 const std::atomic_bool& owner_consent,
                 const std::atomic_bool& stop,
                 const std::function<bool()>& consume_persisted_stage,
                 Reply& output) const;
};
}  // namespace stackchan::standalone

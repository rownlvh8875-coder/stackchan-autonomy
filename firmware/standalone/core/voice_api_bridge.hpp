// SPDX-License-Identifier: MIT
// Portable, synchronous adapter between durable stage-limited voice engine
// and the fixed-host TLS/HTTP + JSON/PCM decoder. No sockets in this header.
#pragma once

#include "offline_voice_cycle.hpp"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <functional>
#include <span>
#include <string>
#include <utility>
#include <vector>

namespace stackchan::standalone {

// A trusted implementation must call spend_dispatch() once immediately before
// it can open a socket, and MUST NOT retry a possibly-billed POST.
class VoiceHttpChannel {
 public:
  virtual ~VoiceHttpChannel() = default;
  virtual bool post_once(const VoiceApiRequest& request,
                         const std::function<bool()>& spend_dispatch,
                         std::vector<uint8_t>& raw_body,
                         uint64_t& completed_ms) = 0;
};

class VoiceReplyCodec {
 public:
  virtual ~VoiceReplyCodec() = default;
  virtual bool transcription(std::span<const uint8_t>, std::string&) = 0;
  virtual bool response_text(std::span<const uint8_t>, std::string&) = 0;
  virtual bool speech_pcm(std::span<const uint8_t>, std::vector<int16_t>&) = 0;
};

// A valid HTTP body alone is not a successful paid step; successful return
// additionally requires its permit was consumed, exact typed decoding,
// no STOP/consent rollback, deadline, and bounded response sizes.
class BoundVoiceApiPort final : public VoiceApiPort {
 public:
  BoundVoiceApiPort(VoiceHttpChannel& http, VoiceReplyCodec& codec,
                    std::function<uint64_t()> monotonic_ms,
                    const std::atomic_bool& stop,
                    const std::atomic_bool& consent,
                    const std::atomic_bool& trusted_clock)
      : http_(http), codec_(codec), now_(std::move(monotonic_ms)),
        stop_(stop), consent_(consent), trusted_(trusted_clock) {}

  VoiceApiReply request(const VoiceApiRequest& req) override {
    VoiceApiReply fail{};
    if (!valid_request(req) || !now_ || stop_.load() || !consent_.load() ||
        !trusted_.load()) return fail;
    const uint64_t before = now_();
    if (before < req.started_ms || before >= req.deadline_ms) return fail;

    std::vector<uint8_t> raw;
    uint64_t completed_ms = 0;
    auto spend = [&]() {
      // The same stop/consent/clock checks apply at the instant the
      // socket-owning HTTP port is allowed to make an outbound request.
      return !stop_.load() && consent_.load() && trusted_.load() &&
             now_() < req.deadline_ms &&
             req.dispatch_permit->consume_once(req.stage, req.session_epoch);
    };
    const bool posted = http_.post_once(req, spend, raw, completed_ms);
    if (!posted || !req.dispatch_permit->used() ||
        stop_.load() || !consent_.load() || !trusted_.load()) return fail;
    const uint64_t after = now_();
    if (after < completed_ms || completed_ms < req.started_ms ||
        completed_ms >= req.deadline_ms || after >= req.deadline_ms ||
        raw.empty()) return fail;

    // Existing TLS port caps JSON to 256 KiB and PCM to 960,000 bytes.
    // This second independent boundary rejects an unsafe mock/adapter too.
    const size_t cap = req.stage == VoiceApiStage::synthesize ?
        20U * 24000U * 2U : 256U * 1024U;
    if (raw.size() > cap) return fail;
    VoiceApiReply reply;
    bool decoded = false;
    if (req.stage == VoiceApiStage::transcribe) {
      decoded = codec_.transcription(raw, reply.utf8_text) &&
                valid_bounded_utf8(reply.utf8_text, 500);
    } else if (req.stage == VoiceApiStage::respond) {
      decoded = codec_.response_text(raw, reply.utf8_text) &&
                valid_bounded_utf8(reply.utf8_text, 300);
    } else {
      decoded = codec_.speech_pcm(raw, reply.pcm24k) &&
                !reply.pcm24k.empty() && reply.pcm24k.size() <= 20U * 24000U;
    }
    std::fill(raw.begin(), raw.end(), uint8_t(0));
    if (!decoded || stop_.load() || !consent_.load() || !trusted_.load())
      return fail;
    const uint64_t decoded_at = now_();
    if (decoded_at < after || decoded_at >= req.deadline_ms) return fail;
    reply.finished_ms = decoded_at;
    reply.http_status = 200;
    reply.success = true;
    return reply;
  }

 private:
  static bool valid_request(const VoiceApiRequest& r) {
    if (!r.dispatch_permit || r.session_epoch == 0 ||
        r.deadline_ms <= r.started_ms ||
        r.deadline_ms - r.started_ms > 30000U ||
        r.model.empty() || r.model.size() > 64U) return false;
    switch (r.stage) {
      case VoiceApiStage::transcribe:
        return r.fixed_path == "/v1/audio/transcriptions" &&
               r.text.empty() && r.voice.empty() && r.language == "ko" &&
               !r.pcm24k.empty() && r.pcm24k.size() <= 8U * 24000U &&
               r.max_output_tokens == 0U && !r.store && !r.pcm_output;
      case VoiceApiStage::respond:
        return r.fixed_path == "/v1/responses" && r.pcm24k.empty() &&
               r.voice.empty() && r.language.empty() &&
               valid_bounded_utf8(r.text, 500U) &&
               r.max_output_tokens == 400U && !r.store && !r.pcm_output;
      case VoiceApiStage::synthesize:
        return r.fixed_path == "/v1/audio/speech" && r.pcm24k.empty() &&
               r.language.empty() && !r.voice.empty() &&
               valid_bounded_utf8(r.text, 300U) &&
               r.max_output_tokens == 0U && !r.store && r.pcm_output;
    }
    return false;
  }

  VoiceHttpChannel& http_;
  VoiceReplyCodec& codec_;
  std::function<uint64_t()> now_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& trusted_;
};

} // namespace stackchan::standalone

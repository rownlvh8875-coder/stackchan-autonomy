// SPDX-License-Identifier: MIT
// Deterministic offline voice-cycle orchestration. It has NO network/JSON/TLS
// implementation and MUST NOT be mistaken for a production OpenAI HTTP client.
#pragma once

#include "persistent_store.hpp"

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace stackchan::standalone {

enum class VoiceApiStage : uint8_t { transcribe, respond, synthesize };

// This in-memory token is emitted ONLY after PersistentGuard consumes the
// durable one-shot stage permit. It binds a single outbound send to the
// session epoch and exact endpoint. It is never stored across reboots.
// Not cryptographic authentication or an API budget by itself.
class OfflineVoiceCycle;
class DispatchPermit final {
 public:
  DispatchPermit(const DispatchPermit&) = delete;
  DispatchPermit& operator=(const DispatchPermit&) = delete;
  bool consume_once(VoiceApiStage stage, uint64_t epoch) {
    if (static_cast<unsigned>(stage) != static_cast<unsigned>(stage_) ||
        epoch != epoch_) return false;
    bool unused = false;
    return used_.compare_exchange_strong(unused, true);
  }
  bool used() const { return used_.load(); }
 private:
  friend class OfflineVoiceCycle;
  explicit DispatchPermit(PaidStage stage, uint64_t epoch)
      : stage_(stage), epoch_(epoch) {}
  PaidStage stage_;
  uint64_t epoch_;
  std::atomic_bool used_{false};
};

struct VoiceApiRequest {
  VoiceApiStage stage;
  std::string_view fixed_path;
  std::string_view model;
  std::string_view text;
  std::string_view voice;
  std::string_view language;
  std::span<const int16_t> pcm24k;
  uint64_t session_epoch = 0;
  uint64_t started_ms = 0;
  uint64_t deadline_ms = 0;
  unsigned max_output_tokens = 0;
  bool store = false;
  bool pcm_output = false;
  // Synchronous: the transport MUST consume once immediately before socket I/O.
  // Null is valid for the old pure mock interface, never for a network adapter.
  DispatchPermit* dispatch_permit = nullptr;
};

// The fake test port returns *already parsed* data; it does not validate
// HTTP chunking, JSON, credentials, MIME types or a real TLS certificate.
struct VoiceApiReply {
  bool success = false;
  int http_status = 0;
  uint64_t finished_ms = 0;
  std::string utf8_text;
  std::vector<int16_t> pcm24k;
};

class VoiceApiPort {
 public:
  virtual ~VoiceApiPort() = default;
  virtual VoiceApiReply request(const VoiceApiRequest& request) = 0;
};

struct VoicePlaybackResult {
  bool complete = false;
  uint64_t finished_ms = 0;
};

class VoiceSpeakerPort {
 public:
  virtual ~VoiceSpeakerPort() = default;
  virtual VoicePlaybackResult play_pcm24k(
      std::span<const int16_t> pcm, uint64_t started_ms) = 0;
};

struct VoiceModelConfig {
  std::string transcription;
  std::string text;
  std::string speech;
  std::string voice;
  bool valid() const {
    return safe_id(transcription) && safe_id(text) && safe_id(speech) &&
           safe_id(voice);
  }
 private:
  static bool safe_id(std::string_view id) {
    if (id.empty() || id.size() > 64) return false;
    for (const unsigned char c : id) {
      const bool alnum = (c >= 'a' && c <= 'z') ||
                         (c >= 'A' && c <= 'Z') ||
                         (c >= '0' && c <= '9');
      if (!alnum && c != '-' && c != '_' && c != '.') return false;
    }
    return true;
  }
};

// Strict well-formed UTF-8 codepoints, not bytes. Reject embedded NUL,
// ASCII controls, overlong forms, surrogates and values above U+10FFFF.
inline bool valid_bounded_utf8(std::string_view text, size_t max_chars) {
  if (text.empty() || text.size() > max_chars * 4U) return false;
  size_t pos = 0, chars = 0;
  while (pos < text.size()) {
    const uint8_t first = static_cast<uint8_t>(text[pos]);
    uint32_t point = 0;
    size_t length = 0;
    uint32_t minimum = 0;
    if (first >= 0x20 && first < 0x7f) {
      point = first; length = 1;
    } else if (first >= 0xc2 && first <= 0xdf) {
      point = first & 0x1fU; length = 2; minimum = 0x80U;
    } else if (first >= 0xe0 && first <= 0xef) {
      point = first & 0x0fU; length = 3; minimum = 0x800U;
    } else if (first >= 0xf0 && first <= 0xf4) {
      point = first & 0x07U; length = 4; minimum = 0x10000U;
    } else {
      return false;
    }
    if (pos + length > text.size()) return false;
    for (size_t i = 1; i < length; ++i) {
      const uint8_t c = static_cast<uint8_t>(text[pos + i]);
      if ((c & 0xc0U) != 0x80U) return false;
      point = (point << 6U) | (c & 0x3fU);
    }
    if (point < minimum || (point >= 0xd800U && point <= 0xdfffU) ||
        point > 0x10ffffU || point == 0x7fU ||
        (point >= 0x80U && point <= 0x9fU)) return false;
    ++chars;
    if (chars > max_chars) return false;
    pos += length;
  }
  return chars > 0;
}

class OfflineVoiceCycle final {
 public:
  static constexpr size_t kMaxRecordedFrames = 8 * 24000; // mono PCM16
  static constexpr size_t kMaxSynthFrames = 20 * 24000;
  static constexpr size_t kMaxTranscriptChars = 500;
  static constexpr size_t kMaxAnswerChars = 300;
  static constexpr uint64_t kStageDeadlineMs = 30000;

  OfflineVoiceCycle(Session& session, PersistentGuard& ledger,
                    VoiceApiPort& api, VoiceSpeakerPort& speaker,
                    const std::atomic_bool& physical_stop,
                    const std::atomic_bool& owner_paid_consent,
                    const std::atomic_bool& trusted_sntp,
                    std::function<bool()> live_readiness = {})
      : session_(session), ledger_(ledger), api_(api), speaker_(speaker),
        stop_(physical_stop), consent_(owner_paid_consent), time_(trusted_sntp),
        readiness_(std::move(live_readiness)) {}

  bool run(std::span<const int16_t> question_pcm24k, uint64_t monotonic_ms,
           uint64_t unix_seconds, const VoiceModelConfig& models) {
    // Any call without consent, enrollment, models or a configured session
    // is rejected BEFORE the durable reservation or a fake transport call.
    if (session_.state() != State::record) return false;
    // A disallowed/cancelled recording must never remain reusable if owner
    // consent, trusted time or cloud enablement changes later.
    if (!cloud_allowed() || !models.valid() ||
        question_pcm24k.empty() || question_pcm24k.size() > kMaxRecordedFrames ||
        !time_.load()) {
      session_.stop();
      ledger_.cancel_permit();
      return false;
    }

    const uint64_t epoch = session_.epoch();
    if (!ledger_.reserve(unix_seconds, time_.load(), consent_.load(), epoch)) {
      (void)session_.recorded(monotonic_ms, epoch, true, false, time_.load());
      ledger_.cancel_permit();
      return false;
    }
    if (!session_.recorded(monotonic_ms, epoch, true, true, time_.load())) {
      ledger_.cancel_permit();
      return false;
    }
    uint64_t now = monotonic_ms;

    VoiceApiRequest stt{VoiceApiStage::transcribe, "/v1/audio/transcriptions",
                        models.transcription, {}, {}, "ko", question_pcm24k,
                        epoch, now, add_deadline(now), 0, false, false};
    const auto transcription = stage(stt, PaidStage::transcribe, State::transcribe, now, epoch);
    if (!transcription || !valid_bounded_utf8(transcription->utf8_text, kMaxTranscriptChars)) {
      (void)session_.transcribed(now, epoch, false);
      ledger_.cancel_permit();
      return false;
    }
    if (!session_.transcribed(now, epoch, true)) { ledger_.cancel_permit(); return false; }

    VoiceApiRequest gpt{VoiceApiStage::respond, "/v1/responses",
                        models.text, transcription->utf8_text, {}, {}, {},
                        epoch, now, add_deadline(now), 400, false, false};
    const auto answer = stage(gpt, PaidStage::respond, State::think, now, epoch);
    if (!answer || !valid_bounded_utf8(answer->utf8_text, kMaxAnswerChars)) {
      (void)session_.thought(now, epoch, false);
      ledger_.cancel_permit();
      return false;
    }
    if (!session_.thought(now, epoch, true)) { ledger_.cancel_permit(); return false; }

    VoiceApiRequest tts{VoiceApiStage::synthesize, "/v1/audio/speech",
                        models.speech, answer->utf8_text, models.voice, {}, {},
                        epoch, now, add_deadline(now), 0, false, true};
    const auto synthesis = stage(tts, PaidStage::synthesize, State::synthesize, now, epoch);
    if (!synthesis || synthesis->pcm24k.empty() ||
        synthesis->pcm24k.size() > kMaxSynthFrames) {
      (void)session_.synthesized(now, epoch, false);
      ledger_.cancel_permit();
      return false;
    }
    if (!session_.synthesized(now, epoch, true)) { ledger_.cancel_permit(); return false; }
    // The real speaker driver must implement a STOP latch + bounded complete
    // playback drain. This port is a host fake, NOT real I2S.
    if (!cloud_allowed() || !time_.load()) {
      session_.stop(); ledger_.cancel_permit(); return false;
    }
    const auto played = speaker_.play_pcm24k(synthesis->pcm24k, now);
    if (!cloud_allowed() || !time_.load()) {
      session_.stop(); ledger_.cancel_permit(); return false;
    }
    const bool complete = played.complete && played.finished_ms >= now;
    const bool accepted = session_.played(
        complete ? played.finished_ms : now, epoch, complete);
    ledger_.cancel_permit();
    return accepted;
  }

 private:
  bool cloud_allowed() const {
    return (!readiness_ || readiness_()) && !stop_.load() && consent_.load() &&
           session_.cloud_enabled();
  }

  static uint64_t add_deadline(uint64_t now) {
    return now > UINT64_MAX - kStageDeadlineMs ? UINT64_MAX :
           now + kStageDeadlineMs;
  }

  std::optional<VoiceApiReply> stage(const VoiceApiRequest& request,
                                      PaidStage permit, State required,
                                      uint64_t& now, uint64_t epoch) {
    session_.tick(now);
    if (!cloud_allowed()) {
      session_.stop(); ledger_.cancel_permit(); return std::nullopt;
    }
    if (session_.state() != required || session_.epoch() != epoch ||
        !time_.load() ||
        !ledger_.authorize_step(permit, consent_.load(), time_.load())) {
      ledger_.cancel_permit();
      return std::nullopt;
    }
    // The NVS budget stage has been spent exactly once. Issue a second,
    // non-billable *transport handoff* bound to this precise stage and epoch.
    // This is NOT another durable reservation and cannot be reused.
    DispatchPermit dispatch(permit, epoch);
    VoiceApiRequest signed_request = request;
    signed_request.dispatch_permit = &dispatch;
    auto reply = api_.request(signed_request);
    if (!cloud_allowed()) {
      session_.stop(); ledger_.cancel_permit(); return std::nullopt;
    }
    if (!reply.success || reply.http_status != 200 ||
        reply.finished_ms < now || reply.finished_ms >= request.deadline_ms) {
      now = std::max(now, reply.finished_ms);
      ledger_.cancel_permit();
      return std::nullopt;
    }
    now = reply.finished_ms;
    session_.tick(now); // Reject overall 90s expiration, stale epoch or clock rollback.
    if (session_.state() != required || session_.epoch() != epoch) {
      ledger_.cancel_permit();
      return std::nullopt;
    }
    return reply;
  }

  Session& session_;
  PersistentGuard& ledger_;
  VoiceApiPort& api_;
  VoiceSpeakerPort& speaker_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& consent_;
  const std::atomic_bool& time_;
  std::function<bool()> readiness_;
};

}  // namespace stackchan::standalone

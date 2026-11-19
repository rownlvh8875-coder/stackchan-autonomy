// SPDX-License-Identifier: MIT
// Offline integration: local wake -> question -> fake STT/GPT/TTS.
#include "wake_voice_entry.hpp"
#include <atomic>
#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>

using namespace stackchan::standalone;

struct Store final : AtomicKv {
  std::vector<uint8_t> budget, profile;
  ReadValue read(std::string_view key, size_t max) override {
    const auto& value = key == "budget" ? budget : profile;
    if (value.empty()) return {ReadCode::missing, {}};
    if (value.size() > max) return {ReadCode::failure, {}};
    return {ReadCode::found, value};
  }
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    if (key == "budget") budget.assign(bytes.begin(), bytes.end());
    else if (key == "wake_profile") profile.assign(bytes.begin(), bytes.end());
    else return false;
    return true;
  }
};
struct Api final : VoiceApiPort {
  int calls = 0;
  VoiceApiReply request(const VoiceApiRequest& req) override {
    assert(req.dispatch_permit != nullptr);
    const auto stage = req.stage;
    assert(req.dispatch_permit->consume_once(stage, req.session_epoch));
    VoiceApiReply reply;
    reply.success = true;
    reply.http_status = 200;
    reply.finished_ms = req.started_ms + 1;
    if (calls == 0) { assert(stage == VoiceApiStage::transcribe); reply.utf8_text = "안녕"; }
    else if (calls == 1) { assert(stage == VoiceApiStage::respond); reply.utf8_text = "반가워요"; }
    else { assert(calls == 2 && stage == VoiceApiStage::synthesize); reply.pcm24k.assign(240, 1); }
    ++calls;
    return reply;
  }
};
struct Speaker final : VoiceSpeakerPort {
  int calls = 0;
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm, uint64_t start) override {
    assert(!pcm.empty()); ++calls;
    return {true, start + 1};
  }
};

int main() {
  std::vector<int16_t> wake(24000);
  for (size_t i = 0; i < wake.size(); ++i) {
    wake[i] = static_cast<int16_t>(10000 * std::sin(2 * kPi * 520.f * i / 24000.f));
  }
  auto feature = wake_mfcc_from_24k(wake);
  assert(feature);
  WakeProfile enrolled;
  enrolled.limit_q8 = 256;
  enrolled.templates.push_back(*feature);
  Store store;
  PersistentGuard ledger(store);
  assert(ledger.save_profile(*encode_wake_profile(enrolled), true));
  assert(ledger.provision_budget(true));
  Session session;
  session.boot(1000, true, true);
  session.cloud_enable(true);  // Fake-only test permission.
  std::atomic_bool stop{false}, consent{true}, trusted{true}, playback{false};
  Api api;
  Speaker speaker;
  WakeVoiceEntry entry(session, enrolled, ledger, api, speaker,
                       stop, consent, trusted, playback);
  const std::vector<int16_t> silence(24000);
  assert(!entry.detect(silence, 1050));
  playback.store(true);
  assert(!entry.detect(wake, 1060));
  playback.store(false);
  auto epoch = entry.detect(wake, 1100);
  assert(epoch && session.state() == State::ready);
  assert(!entry.question_started(1200, *epoch + 1));
  assert(entry.question_started(1200, *epoch));
  playback.store(true);
  assert(!entry.answer(std::vector<int16_t>(2400, 10), 1250, 1800000000,
                       {"stt_test", "gpt_test", "tts_test", "voice_test"}));
  assert(api.calls == 0 && ledger.reserved_conversations() == 0);
  playback.store(false);
  QuestionCapture capture;
  std::array<int16_t, QuestionCapture::kFrame> voiced{}, quiet{};
  voiced.fill(2000);
  assert(!entry.answer_captured(capture, *epoch, 1250, 1800000000,
                                {"stt_test", "gpt_test", "tts_test", "voice_test"}));
  for (int i = 0; i < 3; ++i) (void)capture.push(voiced, false, false);
  for (int i = 0; i < 25; ++i) (void)capture.push(quiet, false, false);
  assert(capture.status() == CaptureResult::ready);
  assert(!entry.answer_captured(capture, *epoch + 1, 1850, 1800000000,
                                {"stt_test", "gpt_test", "tts_test", "voice_test"}));
  assert(capture.audio().empty() && api.calls == 0);
  for (int i = 0; i < 3; ++i) (void)capture.push(voiced, false, false);
  for (int i = 0; i < 25; ++i) (void)capture.push(quiet, false, false);
  assert(entry.answer_captured(capture, *epoch, 1850, 1800000000,
                               {"stt_test", "gpt_test", "tts_test", "voice_test"}));
  assert(capture.audio().empty());
  assert(api.calls == 3 && speaker.calls == 1);
  assert(session.state() == State::cooldown);
  assert(!entry.detect(wake, 1300));
  std::cout << "wake-to-fake-voice integration PASS (no device/API)\n";
}

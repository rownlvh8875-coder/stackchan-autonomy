// SPDX-License-Identifier: MIT
// Fully fake (no network/device) wake -> mic -> question -> STT/GPT/TTS turn.
#include "voice_turn_coordinator.hpp"
#include "guarded_voice_speaker.hpp"

#include <atomic>
#include <cassert>
#include <cmath>
#include <iostream>
#include <span>
#include <vector>

using namespace stackchan::standalone;

struct FakeKv : AtomicKv {
  std::vector<uint8_t> profile, budget;
  ReadValue read(std::string_view key, size_t bound) override {
    const auto& v = key == "budget" ? budget : profile;
    if (v.empty()) return {ReadCode::missing, {}};
    if (v.size() > bound) return {ReadCode::failure, {}};
    return {ReadCode::found, v};
  }
  bool commit(std::string_view key, std::span<const uint8_t> data) override {
    if (key == "wake_profile") profile.assign(data.begin(), data.end());
    else if (key == "budget") budget.assign(data.begin(), data.end());
    else return false;
    return true;
  }
};

struct FakeHardware {
  bool microphone = false, amplifier = false;
  bool fail_mic_off = false, fail_drain = false;
  int mic_on_calls = 0, mic_off_calls = 0, drain_calls = 0;
  AudioHooks hooks() {
    return {
        [this]() { ++mic_off_calls; if (fail_mic_off) return false;
                   microphone = false; return true; },
        [this]() { amplifier = false; return true; },
        []() { return true; },
        [this]() { ++mic_on_calls; microphone = true; return true; },
        []() { return true; },
        [this]() { amplifier = true; return true; },
        [this]() { ++drain_calls; return !fail_drain; }
    };
  }
};

struct FakeMic : MonoMicReader {
  FakeHardware& hw;
  std::atomic_bool* external_stop = nullptr;
  int calls = 0, fail_on = -1, stop_on = -1, voiced_reads = 8;
  explicit FakeMic(FakeHardware& hardware) : hw(hardware) {}
  bool read_10ms(std::span<int16_t> pcm) override {
    assert(hw.microphone && !hw.amplifier && pcm.size() == 240);
    const int call = calls++;
    if (external_stop && call == stop_on) external_stop->store(true);
    if (call == fail_on) return false;
    for (int16_t& v : pcm) v = call < voiced_reads ? 2000 : 0;
    return true;
  }
};
struct FakeApi : VoiceApiPort {
  FakeHardware& hw;
  int calls = 0;
  explicit FakeApi(FakeHardware& h) : hw(h) {}
  VoiceApiReply request(const VoiceApiRequest& req) override {
    assert(!hw.microphone && !hw.amplifier);
    assert(req.dispatch_permit &&
           req.dispatch_permit->consume_once(req.stage, req.session_epoch));
    VoiceApiReply reply;
    reply.success = true;
    reply.http_status = 200;
    reply.finished_ms = req.started_ms + 1;
    if (calls == 0) {
      assert(req.stage == VoiceApiStage::transcribe);
      reply.utf8_text = "테스트 질문";
    } else if (calls == 1) {
      assert(req.stage == VoiceApiStage::respond);
      reply.utf8_text = "테스트 답변";
    } else {
      assert(calls == 2 && req.stage == VoiceApiStage::synthesize);
      reply.pcm24k.assign(240, 1);
    }
    ++calls;
    return reply;
  }
};
struct FakeSpeaker : VoiceSpeakerPort {
  FakeHardware& hw;
  int calls = 0;
  bool fail_output = false;
  std::atomic_bool* stop_during_output = nullptr;
  explicit FakeSpeaker(FakeHardware& h) : hw(h) {}
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,
                                  uint64_t started_ms) override {
    assert(!hw.microphone && hw.amplifier && !pcm.empty());
    ++calls;
    if (stop_during_output) stop_during_output->store(true);
    return {!fail_output, started_ms + 1};
  }
};

struct Fixture {
  FakeKv kv;
  PersistentGuard ledger{kv};
  Session session;
  WakeProfile enrolled;
  std::atomic_bool stop{false}, consent{true}, trusted{true}, speaker_busy{false};
  FakeHardware hardware;
  AudioGuard audio{hardware.hooks()};
  FakeMic mic{hardware};
  FakeApi api{hardware};
  FakeSpeaker sink{hardware};
  GuardedVoiceSpeaker speaker{audio, sink, stop, consent, speaker_busy};
  WakeVoiceEntry entry{session, enrolled, ledger, api, speaker,
                       stop, consent, trusted, speaker_busy};
  MicFrameBridge bridge{mic, stop, speaker_busy};
  VoiceTurnCoordinator controller{session, ledger, entry, bridge, audio,
                                  stop, consent, speaker_busy};
  VoiceModelConfig models{"stt_test", "gpt_test", "tts_test", "voice_test"};
  uint64_t epoch = 0;

  Fixture() {
    // Exercise the actual local MFCC/DTW wake matching path with a synthetic
    // frequency fixture; this is NOT an acoustic Korean recognizer trial.
    static const std::vector<int16_t> wake_pcm = [] {
      std::vector<int16_t> pcm(24000);
      for (size_t i = 0; i < pcm.size(); ++i) {
        const float phase = 2 * kPi * 520.f * static_cast<float>(i) / 24000.f;
        pcm[i] = static_cast<int16_t>(10000 * std::sin(phase));
      }
      return pcm;
    }();
    static const auto feature = wake_mfcc_from_24k(wake_pcm);
    assert(feature);
    enrolled.limit_q8 = 256;
    enrolled.templates.push_back(*feature);
    assert(ledger.save_profile(*encode_wake_profile(enrolled), true));
    assert(ledger.provision_budget(true));
    session.boot(1000, true, true);
    session.cloud_enable(true);  // Fake API only, never production default.
    assert(audio.initialize(true, true));
    const std::vector<int16_t> silence(24000, 0);
    assert(!entry.detect(silence, 1050));
    auto wake = entry.detect(wake_pcm, 1100);
    assert(wake);
    epoch = *wake;
  }

  VoiceTurnStep tick(int frame) {
    return controller.poll(1140 + static_cast<uint64_t>(20 * frame),
                           1800000000, models);
  }
};

int main() {
  {
    Fixture x;
    assert(!x.controller.arm(x.epoch + 1, 1120));
    assert(x.hardware.mic_on_calls == 0);
    assert(x.controller.arm(x.epoch, 1120));
    assert(x.hardware.microphone);
    for (int frame = 0; frame < 28; ++frame) {
      const auto status = x.tick(frame);
      if (frame < 2) assert(status == VoiceTurnStep::waiting_for_speech);
      else assert(status == VoiceTurnStep::recording);
    }
    assert(x.tick(28) == VoiceTurnStep::answered);
    assert(!x.hardware.microphone && !x.controller.active());
    assert(x.api.calls == 3 && x.sink.calls == 1);
    assert(!x.hardware.amplifier && !x.speaker_busy.load());
    assert(x.hardware.drain_calls == 1 && x.audio.state() == AudioState::idle);
    assert(x.ledger.reserved_conversations() == 1);
    assert(x.session.state() == State::cooldown);
    assert(x.tick(29) == VoiceTurnStep::inactive);
    assert(x.api.calls == 3);
  }
  {
    Fixture x;
    x.consent.store(false);
    assert(!x.controller.arm(x.epoch, 1120));
    assert(x.hardware.mic_on_calls == 0);
  }
  {
    Fixture x;
    assert(x.controller.arm(x.epoch, 1120));
    x.mic.fail_on = 1; // Two 10ms reads are not atomic.
    assert(x.tick(0) == VoiceTurnStep::aborted);
    assert(x.audio.stopped() && !x.hardware.microphone);
    assert(x.api.calls == 0 && x.ledger.reserved_conversations() == 0);
    assert(!x.controller.arm(x.epoch, 1180)); // One-way fault latch.
  }
  {
    Fixture x;
    assert(x.controller.arm(x.epoch, 1120));
    x.mic.external_stop = &x.stop;
    x.mic.stop_on = 0; // STOP during the first physical read.
    assert(x.tick(0) == VoiceTurnStep::aborted);
    assert(x.mic.calls == 1 && !x.hardware.microphone);
    assert(x.api.calls == 0);
  }
  {
    Fixture x;
    assert(x.controller.arm(x.epoch, 1120));
    x.speaker_busy.store(true);
    assert(x.tick(0) == VoiceTurnStep::aborted);
    assert(x.mic.calls == 0 && !x.hardware.microphone);
  }
  {
    Fixture x;
    assert(x.controller.arm(x.epoch, 1120));
    x.consent.store(false);
    assert(x.tick(0) == VoiceTurnStep::aborted);
    assert(x.api.calls == 0);
  }
  {
    Fixture x;
    assert(x.controller.arm(x.epoch, 1120));
    // Session's 5s ready deadline elapsed before speech began.
    assert(x.controller.poll(6150, 1800000000, x.models) ==
           VoiceTurnStep::aborted);
    assert(x.api.calls == 0 && x.controller.faulted());
  }
  {
    Fixture x;
    assert(x.controller.arm(x.epoch, 1120));
    x.hardware.fail_mic_off = true;
    for (int frame = 0; frame < 28; ++frame) {
      assert(x.tick(frame) != VoiceTurnStep::answered);
    }
    assert(x.tick(28) == VoiceTurnStep::aborted);
    assert(x.api.calls == 0 && x.audio.state() == AudioState::fault);
  }
  {
    Fixture x;
    x.sink.fail_output = true;
    assert(x.controller.arm(x.epoch, 1120));
    for (int frame = 0; frame < 28; ++frame)
      assert(x.tick(frame) != VoiceTurnStep::aborted);
    assert(x.tick(28) == VoiceTurnStep::aborted);
    assert(x.sink.calls == 1 && x.api.calls == 3);
    assert(x.speaker.latched() && x.speaker_busy.load());
    assert(!x.hardware.microphone && !x.hardware.amplifier);
    assert(x.audio.stopped() && x.controller.faulted());
  }
  {
    Fixture x;
    x.sink.stop_during_output = &x.stop;
    assert(x.controller.arm(x.epoch, 1120));
    for (int frame = 0; frame < 28; ++frame)
      assert(x.tick(frame) != VoiceTurnStep::aborted);
    assert(x.tick(28) == VoiceTurnStep::aborted);
    assert(x.stop.load() && x.speaker.latched());
    assert(x.sink.calls == 1 && !x.hardware.amplifier);
  }
  {
    Fixture x;
    x.hardware.fail_drain = true;
    assert(x.controller.arm(x.epoch, 1120));
    for (int frame = 0; frame < 28; ++frame)
      assert(x.tick(frame) != VoiceTurnStep::aborted);
    assert(x.tick(28) == VoiceTurnStep::aborted);
    assert(x.hardware.drain_calls == 1 && x.speaker.latched());
    assert(x.audio.state() == AudioState::fault);
    assert(!x.hardware.amplifier && x.speaker_busy.load());
  }
  std::cout << "voice turn coordinator: PASS (offline, fake audio/API)\n";
}

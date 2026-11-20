// Pure host test of paid-stage bridge. There are NO HTTP sockets, device
// drivers, API keys, microphone, audio files, or live OpenAI requests.
#include "voice_api_bridge.hpp"

#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;

class FakeKv final : public AtomicKv {
 public:
  std::vector<uint8_t> profile, budget;
  ReadValue read(std::string_view key, size_t max) override {
    const auto& bytes = key == "budget" ? budget : profile;
    if (bytes.empty()) return {ReadCode::missing, {}};
    if (bytes.size() > max) return {ReadCode::failure, {}};
    return {ReadCode::found, bytes};
  }
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    if (key == "budget") budget.assign(bytes.begin(), bytes.end());
    else if (key == "wake_profile") profile.assign(bytes.begin(), bytes.end());
    else return false;
    return true;
  }
};

class FakeHttp final : public VoiceHttpChannel {
 public:
  int calls=0, fail_at=-1, stop_at=-1, revoke_at=-1;
  int late_at=-1, skip_ticket_at=-1, retry_ticket_at=-1;
  uint64_t* clock=nullptr;
  std::atomic_bool* stop=nullptr;
  std::atomic_bool* consent=nullptr;

  bool post_once(const VoiceApiRequest& req, const std::function<bool()>& spend,
                 std::vector<uint8_t>& raw, uint64_t& completed_ms) override {
    const int index = calls++;
    assert(index < 3);
    assert(req.session_epoch > 0);
    if (index == 0) {
      assert(req.stage == VoiceApiStage::transcribe);
      assert(req.fixed_path == "/v1/audio/transcriptions");
      assert(req.pcm24k.size() == 2400);
    } else if (index == 1) {
      assert(req.stage == VoiceApiStage::respond);
      assert(req.fixed_path == "/v1/responses");
    } else {
      assert(req.stage == VoiceApiStage::synthesize);
      assert(req.fixed_path == "/v1/audio/speech");
    }
    if (index != skip_ticket_at) {
      if (!spend()) return false;
      if (index == retry_ticket_at) assert(!spend());
    }
    if (index == stop_at && stop) stop->store(true);
    if (index == revoke_at && consent) consent->store(false);
    completed_ms = index == late_at ? req.deadline_ms + 1 : req.started_ms + 10;
    if (clock) *clock = completed_ms;
    if (index == fail_at) return false;
    const char* data = index == 0 ? "STT" : index == 1 ? "GPT" : "PCM";
    raw.assign(data, data + 3);
    return true;
  }
};

class FakeCodec final : public VoiceReplyCodec {
 public:
  bool transcription(std::span<const uint8_t> raw, std::string& out) override {
    if (std::string(raw.begin(), raw.end()) != "STT") return false;
    out = "조수야 누구야?";
    return true;
  }
  bool response_text(std::span<const uint8_t> raw, std::string& out) override {
    if (std::string(raw.begin(), raw.end()) != "GPT") return false;
    out = "테스트 답변입니다";
    return true;
  }
  bool speech_pcm(std::span<const uint8_t> raw,
                  std::vector<int16_t>& out) override {
    if (std::string(raw.begin(), raw.end()) != "PCM") return false;
    out.assign(240, 20);
    return true;
  }
};

class FakeSpeaker final : public VoiceSpeakerPort {
 public:
  int calls=0;
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> frames,
                                  uint64_t started_ms) override {
    ++calls;
    assert(frames.size() == 240);
    return {true, started_ms + 5};
  }
};

struct Fixture {
  FakeKv kv;
  PersistentGuard ledger{kv};
  Session session;
  std::atomic_bool stop{false}, consent{true}, trusted{true};
  uint64_t clock_ms=1250;
  FakeHttp http;
  FakeCodec decoder;
  BoundVoiceApiPort port{http, decoder, [this]() { return clock_ms; },
                         stop, consent, trusted};
  FakeSpeaker speaker;
  VoiceModelConfig models{"stt_test","gpt_test","tts_test","voice_test"};
  std::vector<int16_t> speech = std::vector<int16_t>(2400, 100);
  Fixture() {
    http.clock = &clock_ms;
    http.stop = &stop;
    http.consent = &consent;
    WakeProfile p;
    p.limit_q8 = 512;
    WakeFeature sample;
    sample.quantized.fill(1);
    p.templates.push_back(sample);
    assert(ledger.save_profile(*encode_wake_profile(p), true));
    assert(ledger.provision_budget(true));
    session.boot(1000, true, true);
    session.cloud_enable(true);
    const auto epoch = session.wake(1100);
    assert(epoch);
    assert(session.speech_started(1200,*epoch));
  }
  bool run() {
    OfflineVoiceCycle cycle(session,ledger,port,speaker,stop,consent,trusted);
    return cycle.run(speech,1250,1800000000,models);
  }
};

int main() {
  {
    Fixture f;
    assert(f.run());
    assert(f.http.calls == 3 && f.speaker.calls == 1);
    assert(f.ledger.reserved_conversations() == 1);
    assert(!f.ledger.permit_active());
    assert(!f.run() && f.http.calls == 3);
  }
  {
    Fixture f; f.http.retry_ticket_at=0;
    assert(f.run() && f.http.calls==3);
  }
  {
    Fixture f; f.http.skip_ticket_at=0;
    assert(!f.run() && f.http.calls==1 && f.speaker.calls==0);
    assert(f.ledger.reserved_conversations()==1);
  }
  {
    Fixture f; f.http.fail_at=0;
    assert(!f.run() && f.http.calls==1 && f.speaker.calls==0);
    assert(f.ledger.reserved_conversations()==1);
  }
  {
    Fixture f; f.http.fail_at=1;
    assert(!f.run() && f.http.calls==2 && f.speaker.calls==0);
  }
  {
    Fixture f; f.http.stop_at=0;
    assert(!f.run() && f.http.calls==1 && f.session.state()==State::stopped);
  }
  {
    Fixture f; f.http.revoke_at=1;
    assert(!f.run() && f.http.calls==2 && f.speaker.calls==0);
    assert(f.ledger.reserved_conversations()==1);
  }
  {
    Fixture f; f.http.late_at=0;
    assert(!f.run() && f.http.calls==1 && f.speaker.calls==0);
  }
  {
    Fixture f; f.clock_ms=32000;
    assert(!f.run() && f.http.calls==0 && f.ledger.reserved_conversations()==1);
  }
  {
    Fixture f;
    VoiceApiRequest forged{VoiceApiStage::respond, "/v1/responses",
        "gpt_test", "안녕", {}, {}, {}, 123, 1000, 2000, 400, false, false};
    assert(!f.port.request(forged).success && f.http.calls==0);
  }
  {
    Fixture f;
    f.trusted.store(false);
    assert(!f.run() && f.http.calls==0 && f.ledger.reserved_conversations()==0);
  }
  {
    Fixture f; f.consent.store(false);
    assert(!f.run() && f.http.calls==0 && f.ledger.reserved_conversations()==0);
  }
  std::cout << "K151 paid-stage bridge: 12 offline cases PASS (no sockets)\n";
}

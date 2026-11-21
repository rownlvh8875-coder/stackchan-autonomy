// Pure host test of paid-stage bridge. There are NO HTTP sockets, device
// drivers, API keys, microphone, audio files, or live OpenAI requests.
#include "voice_api_bridge.hpp"
#include "k151_voice_decode.hpp"
#include "wire_memory_probe.hpp"

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
    if (index == 0) {
      const std::string body = R"({"text":"조수야 누구야?"})";
      raw.assign(body.begin(), body.end());
    } else if (index == 1) {
      const std::string body =
          R"({"status":"completed","error":null,"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"테스트 답변입니다"}]}]})";
      raw.assign(body.begin(), body.end());
    } else {
      raw = {0, 128, 255, 127}; // 2 signed PCM16 samples
    }
    return true;
  }
};

// This is the real cJSON/PCM decoder linked into ESP-IDF, not a mock.
class ActualCodec final : public VoiceReplyCodec {
 public:
  bool transcription(std::span<const uint8_t> raw, std::string& out) override {
    return K151VoiceDecoder::transcription(raw,out);
  }
  bool response_text(std::span<const uint8_t> raw, std::string& out) override {
    return K151VoiceDecoder::response_text(raw,out);
  }
  bool speech_pcm(std::span<const uint8_t> raw,
                  std::vector<int16_t>& out) override {
    return K151VoiceDecoder::speech_pcm(raw,out);
  }
};

class FakeSpeaker final : public VoiceSpeakerPort {
 public:
  int calls=0;
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> frames,
                                  uint64_t started_ms) override {
    ++calls;
    assert(frames.size() == 2);
    assert(frames[0] == -32768 && frames[1] == 32767);
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
  ActualCodec decoder;
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
    std::vector<int16_t> decoded;
    unsigned observed = 0;
    const auto observe = [&](httpwire::Endpoint endpoint, const auto& raw, const auto& pcm) {
      assert(raw.size() == httpwire::response_cap(endpoint));
      assert(raw.capacity() <= httpwire::response_cap(endpoint));
      if (observed++ == 0) {
        assert(endpoint == httpwire::Endpoint::responses && pcm.empty());
      } else {
        assert(endpoint == httpwire::Endpoint::speech);
        assert(pcm.size() == OfflineVoiceCycle::kMaxSynthFrames);
        assert(std::all_of(pcm.begin(), pcm.end(), [](auto v) { return v == 0; }));
      }
      return true;
    };
    assert(probe_wire_memory(decoded, [] { return true; }, observe));
    assert(observed == 2);
    decoded.clear();
    observed = 0;
    // Cancel while filling the first body. No decoded data or peak observation.
    unsigned calls = 0;
    assert(!probe_wire_memory(decoded, [&] { return ++calls < 16; }, observe));
    assert(observed == 0 && decoded.empty() && calls == 16);
  }
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
  std::cout << "K151 paid-stage + real cJSON/PCM decoder: offline PASS\n";
}

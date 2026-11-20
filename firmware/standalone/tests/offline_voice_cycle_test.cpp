// Offline fake STT -> GPT -> TTS contract; ZERO sockets, secrets or hardware.
#include "offline_voice_cycle.hpp"
#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <vector>

using namespace stackchan::standalone;

struct FakeKv : AtomicKv {
  std::vector<uint8_t> budget, profile;
  ReadValue read(std::string_view key, size_t bound) override {
    const auto& value = key=="budget" ? budget : profile;
    if (value.empty()) return {ReadCode::missing,{}};
    if (value.size() > bound) return {ReadCode::failure,{}};
    return {ReadCode::found,value};
  }
  bool commit(std::string_view key, std::span<const uint8_t> value) override {
    if (key=="budget") budget.assign(value.begin(),value.end());
    else if (key=="wake_profile") profile.assign(value.begin(),value.end());
    else return false;
    return true;
  }
};

struct FakeApi : VoiceApiPort {
  int calls = 0;
  int fail_at = -1, stop_at = -1, delay_at = -1, overflow_at = -1;
  int disable_cloud_at = -1;
  Session* session = nullptr;
  bool invalid_utf8 = false;
  uint64_t duration = 5;
  std::atomic_bool* stop = nullptr;
  std::vector<VoiceApiStage> stages;
  VoiceApiReply request(const VoiceApiRequest& req) override {
    const int index = calls++;
    stages.push_back(req.stage);
    assert(!req.store);
    assert(req.session_epoch != 0 && req.deadline_ms > req.started_ms);
    if (index == 0) {
      assert(req.fixed_path=="/v1/audio/transcriptions");
      assert(req.language=="ko" && req.pcm24k.size()==2400);
    } else if (index == 1) {
      assert(req.fixed_path=="/v1/responses");
      assert(req.max_output_tokens==400);
      assert(req.text=="조수야 누구야?");
    } else if (index == 2) {
      assert(req.fixed_path=="/v1/audio/speech");
      assert(req.pcm_output && req.voice=="voice_test");
      assert(req.text=="테스트 답변입니다");
    } else {
      assert(false); // No retry or fourth request
    }
    if (stop && index == stop_at) stop->store(true);
    if (session && index == disable_cloud_at) session->cloud_enable(false);
    VoiceApiReply out;
    out.success = index != fail_at;
    out.http_status = out.success ? 200 : 500;
    out.finished_ms = req.started_ms + (index == delay_at ? 35000 : duration);
    if (index == 0) {
      out.utf8_text = "조수야 누구야?";
      if (invalid_utf8) out.utf8_text = std::string("\xed\xa0\x80", 3);
      if (index == overflow_at) out.utf8_text = std::string(501,'a');
    } else if (index == 1) {
      out.utf8_text = "테스트 답변입니다";
      if (index == overflow_at) out.utf8_text = std::string(301,'b');
    } else {
      out.pcm24k.assign(index == overflow_at ? 480001 : 240, 1);
    }
    return out;
  }
};

struct FakeSpeaker : VoiceSpeakerPort {
  int calls=0;
  bool complete=true;
  std::atomic_bool* stop=nullptr;
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,
                                 uint64_t started_ms) override {
    ++calls;
    assert(!pcm.empty() && pcm.size()<=480000);
    if (stop) stop->store(true);
    return {complete,started_ms+5};
  }
};

struct Fixture {
  FakeKv db;
  PersistentGuard guard{db};
  Session session;
  std::atomic_bool stop{false}, consent{true}, trusted{true};
  FakeApi api;
  FakeSpeaker speaker;
  VoiceModelConfig models{"stt_test", "gpt_test", "tts_test", "voice_test"};
  std::vector<int16_t> recorded = std::vector<int16_t>(2400, 100);
  uint64_t epoch = 0;
  Fixture() {
    WakeProfile profile;
    WakeFeature f;
    f.quantized.fill(3);
    profile.limit_q8=512; profile.templates.push_back(f);
    assert(guard.save_profile(*encode_wake_profile(profile),true));
    assert(guard.provision_budget(true));
    session.boot(1000,true,true);
    session.cloud_enable(true); // TEST OWNER ONLY, not firmware default.
    auto wake=session.wake(1100);
    assert(wake);
    epoch=*wake;
    assert(session.speech_started(1200,epoch));
  }
  bool run(uint64_t epoch_seconds=1800000000) {
    OfflineVoiceCycle cycle(session,guard,api,speaker,stop,consent,trusted);
    return cycle.run(recorded,1250,epoch_seconds,models);
  }
};

int main() {
  {
    Fixture x;
    assert(x.run()); assert(x.api.calls==3 && x.speaker.calls==1);
    assert(x.session.state()==State::cooldown);
    assert(x.guard.reserved_conversations()==1 && !x.guard.permit_active());
    assert(!x.run()); assert(x.api.calls==3);
  }
  {
    Fixture x; x.api.fail_at=0;
    assert(!x.run() && x.api.calls==1 && x.speaker.calls==0);
    assert(x.session.state()==State::error);
    assert(x.guard.reserved_conversations()==1 && !x.guard.permit_active());
  }
  {
    Fixture x; x.api.fail_at=1;
    assert(!x.run() && x.api.calls==2 && x.speaker.calls==0);
  }
  {
    Fixture x; x.api.stop=&x.stop; x.api.stop_at=0;
    assert(!x.run() && x.api.calls==1 && x.session.state()==State::stopped);
    assert(x.guard.reserved_conversations()==1 && x.speaker.calls==0);
  }
  {
    Fixture x; x.api.stop=&x.stop; x.api.stop_at=1;
    assert(!x.run() && x.api.calls==2 && x.speaker.calls==0);
  }
  {
    Fixture x; x.api.session=&x.session; x.api.disable_cloud_at=0;
    assert(!x.run() && x.api.calls==1 && x.speaker.calls==0);
    assert(x.session.state()==State::stopped);
  }
  {
    Fixture x; x.api.delay_at=0;
    assert(!x.run() && x.api.calls==1 && x.speaker.calls==0);
    assert(x.session.state()==State::error);
  }
  {
    Fixture x; x.api.overflow_at=0;
    assert(!x.run() && x.api.calls==1 && x.speaker.calls==0);
  }
  {
    Fixture x; x.api.overflow_at=1;
    assert(!x.run() && x.api.calls==2 && x.speaker.calls==0);
  }
  {
    Fixture x; x.api.overflow_at=2;
    assert(!x.run() && x.api.calls==3 && x.speaker.calls==0);
  }
  {
    Fixture x; x.api.invalid_utf8=true;
    assert(!x.run() && x.api.calls==1);
  }
  {
    Fixture x; x.consent.store(false);
    assert(!x.run() && x.api.calls==0);
    assert(x.guard.reserved_conversations()==0);
  }
  {
    Fixture x; x.trusted.store(false);
    assert(!x.run() && x.api.calls==0);
    assert(x.guard.reserved_conversations()==0);
  }
  {
    Fixture x; x.session.cloud_enable(false);
    assert(!x.run() && x.api.calls==0);
    assert(x.guard.reserved_conversations()==0);
  }
  {
    Fixture x; x.stop.store(true);
    assert(!x.run() && x.api.calls==0);
    assert(x.session.state()==State::stopped);
    assert(x.guard.reserved_conversations()==0);
    x.stop.store(false);
    // An old captured utterance is not eligible for a delayed paid dispatch.
    assert(!x.run() && x.api.calls==0);
  }
  {
    Fixture x; x.recorded.resize(192001);
    assert(!x.run() && x.api.calls==0);
  }
  {
    Fixture x; x.speaker.complete=false;
    assert(!x.run() && x.api.calls==3 && x.speaker.calls==1);
    assert(x.session.state()==State::error);
  }
  {
    Fixture x; x.speaker.stop=&x.stop;
    assert(!x.run() && x.api.calls==3 && x.speaker.calls==1);
    assert(x.session.state()==State::stopped);
  }
  {
    Fixture x; x.models.text="bad\nmodel";
    assert(!x.run() && x.api.calls==0);
  }
  assert(valid_bounded_utf8("한글 테스트",10));
  assert(!valid_bounded_utf8(std::string("\xed\xa0\x80",3),100));
  assert(!valid_bounded_utf8(std::string("\xc0\x80",2),100));
  assert(!valid_bounded_utf8(std::string("\xf4\x90\x80\x80",4),100));
  assert(!valid_bounded_utf8("a\n",100));
  std::cout << "offline STT/GPT/TTS orchestration: PASS (no network)\n";
}

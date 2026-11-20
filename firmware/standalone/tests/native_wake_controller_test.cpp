// SPDX-License-Identifier: MIT
// Real stream/session/voice pipeline; fake hardware, neural model, API and sink.
#include "native_wake_controller.hpp"
#include "voice_turn_coordinator.hpp"
#include "guarded_voice_speaker.hpp"
#include <array>
#include <atomic>
#include <cassert>
#include <functional>
#include <iostream>
#include <optional>
#include <string_view>
#include <vector>
using namespace stackchan::standalone;
struct Store:AtomicKv {
  std::vector<uint8_t> budget;
  ReadValue read(std::string_view k,size_t bound) override {
    if (k!="budget" || budget.empty()) return {ReadCode::missing,{}};
    if (budget.size()>bound) return {ReadCode::failure,{}};
    return {ReadCode::found,budget};
  }
  bool commit(std::string_view k,std::span<const uint8_t> b) override {
    if(k!="budget") { return false; }
    budget.assign(b.begin(),b.end()); return true;
  }
};
struct Hardware {
  bool mic=false,amp=false,fail_close=false;
  int on=0;
  AudioHooks hooks() { return {
    [this]{if(fail_close)return false;mic=false;return true;},
    [this]{amp=false;return true;}, []{return true;},
    [this]{++on;mic=true;return true;}, []{return true;},
    [this]{amp=true;return true;}, []{return true;}}; }
};
struct Mic:MonoMicReader {
  Hardware& hw; bool question=false,fail=false; int calls=0;
  std::function<void()> hook;
  explicit Mic(Hardware& h,bool q=false):hw(h),question(q){}
  bool read_10ms(std::span<int16_t> pcm) override {
    assert(hw.mic && !hw.amp && pcm.size()==240);
    if(hook)hook();
    ++calls; if(fail)return false;
    for(auto& v:pcm)v=question?(calls<=8?2000:0):-7000;
    return true;
  }
};
struct Model:NativeWakePort {
  bool available=true,reset_ok=true;
  NativeWakeFormat fmt{16000,480,1,16};
  NativeWakeResult reply=NativeWakeResult::detected;
  int calls=0,resets=0;
  std::vector<std::vector<int16_t>> frames;
  std::function<void()> hook;
  bool ready() const override {return available;}
  NativeWakeFormat format() const override {return fmt;}
  NativeWakeResult detect(std::span<int16_t> pcm) override {
    ++calls; frames.emplace_back(pcm.begin(),pcm.end());
    if(hook) { hook(); }
    return reply;
  }
  bool reset() override {++resets; return reset_ok;}
};
struct Api:VoiceApiPort {
  Hardware& hw; int calls=0;
  explicit Api(Hardware& h):hw(h){}
  VoiceApiReply request(const VoiceApiRequest& r) override {
    assert(!hw.mic && !hw.amp);
    assert(r.dispatch_permit && r.dispatch_permit->consume_once(r.stage,r.session_epoch));
    VoiceApiReply v; v.success=true;v.http_status=200;v.finished_ms=r.started_ms+1;
    if(calls==0){
      assert(r.stage==VoiceApiStage::transcribe);
      for(auto sample:r.pcm24k)assert(sample==0 || sample==2000);
      v.utf8_text="질문";
    }
    else if(calls==1){assert(r.stage==VoiceApiStage::respond);v.utf8_text="답변";}
    else {assert(calls==2 && r.stage==VoiceApiStage::synthesize);v.pcm24k.assign(240,1);}
    ++calls;return v;
  }
};
struct Sink:VoiceSpeakerPort {
  Hardware& hw; int calls=0;
  explicit Sink(Hardware& h):hw(h){}
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,uint64_t now) override {
    assert(!hw.mic && hw.amp && !pcm.empty());++calls;return {true,now+1};
  }
};
struct Fixture {
  Store store;PersistentGuard ledger{store};Session session;
  std::atomic_bool stop{false},consent{true},time{true},busy{false};
  Hardware hardware;AudioGuard audio{hardware.hooks()};
  Mic wake_mic{hardware},question_mic{hardware,true};Model model;
  Api api{hardware};Sink sink{hardware};
  GuardedVoiceSpeaker speaker{audio,sink,stop,consent,busy};
  VoiceDialogEntry entry{session,ledger,api,speaker,stop,consent,time,busy};
  MicFrameBridge bridge{question_mic,stop,busy};
  VoiceTurnCoordinator turn{session,ledger,entry,bridge,audio,stop,consent,busy};
  std::optional<NativeWakeController> native;
  VoiceModelConfig models{"stt_test","gpt_test","tts_test","voice_test"};
  Fixture() {
    assert(ledger.provision_budget(true));
    // No personal SWK1 profile is manufactured/saved for this provider.
    session.boot(1000,true,model.ready());
    assert(!session.cloud_enabled());
    assert(audio.initialize(true,true));
    native.emplace(session,entry,wake_mic,audio,model);
  }
  NativeWakeEvent wake() {
    assert(native->begin(1000));
    assert(native->poll(1010).step==NativeWakeStep::listening);
    assert(native->poll(1020).step==NativeWakeStep::listening);
    return native->poll(1030);
  }
};
int main(int argc,char** argv) {
  assert(argc==2);const std::string_view test=argv[1];
  Fixture x;
  if(test=="turn" || test=="cloud_off") {
    if(test=="turn")x.session.cloud_enable(true); // Fake requests only.
    const auto event=x.wake();
    assert(event.step==NativeWakeStep::detected && event.epoch);
    assert(x.session.state()==State::ready && x.audio.state()==AudioState::idle);
    assert(!x.hardware.mic && !x.native->active());
    assert(x.turn.arm(*event.epoch,1040));
    VoiceTurnStep result=VoiceTurnStep::inactive;
    for(int i=0;i<=28;++i)result=x.turn.poll(1060+uint64_t(i)*20,1800000000,x.models);
    if(test=="turn") {
      assert(result==VoiceTurnStep::answered && x.api.calls==3 && x.sink.calls==1);
      assert(!x.hardware.mic && !x.hardware.amp && !x.busy.load());
      assert(x.session.state()==State::cooldown && x.ledger.reserved_conversations()==1);
      assert(!x.native->begin(1700));
      assert(x.native->begin(2200));
      (void)x.native->poll(2210);(void)x.native->poll(2220);
      auto next=x.native->poll(2230);
      assert(next.step==NativeWakeStep::detected && next.epoch && *next.epoch>*event.epoch);
      assert(x.api.calls==3);
    } else assert(result==VoiceTurnStep::aborted && x.api.calls==0);
  } else if(test=="guard_stop" || test=="guard_consent" || test=="guard_speaker") {
    if(test=="guard_stop")x.stop=true;
    if(test=="guard_consent")x.consent=false;
    if(test=="guard_speaker")x.busy=true;
    assert(!x.native->begin(1000));
    assert(x.wake_mic.calls==0 && x.hardware.on==0 && x.model.calls==0);
  } else if(test=="missing_model") {
    x.model.available=false;assert(!x.native->begin(1000));
    assert(x.hardware.on==0 && x.model.calls==0);
  } else if(test=="bad_format") {
    for(int i=0;i<6;++i) {
      Fixture a;
      if(i==0)a.model.fmt.sample_rate_hz=24000;
      if(i==1)a.model.fmt.channels=2;
      if(i==2)a.model.fmt.bits_per_sample=32;
      if(i==3)a.model.fmt.chunk_samples=0;
      if(i==4)a.model.fmt.chunk_samples=159;
      if(i==5)a.model.fmt.chunk_samples=2049;
      assert(!a.native->begin(1000));
      assert(a.native->faulted() && a.hardware.on==0 && a.model.calls==0);
    }
  } else if(test=="chunking") {
    x.model.fmt.chunk_samples=512;x.model.reply=NativeWakeResult::none;
    assert(x.native->begin(1000));
    for(int i=1;i<=10;++i)assert(x.native->poll(1000+i*10).step==NativeWakeStep::listening);
    assert(x.model.calls==3 && x.wake_mic.calls==10);
    for(const auto& frame:x.model.frames)assert(frame.size()==512);
    assert(x.native->cancel().step==NativeWakeStep::rejected);
    assert(!x.hardware.mic && x.native->faulted() && !x.native->begin(1200));
  } else if(test=="large_chunk") {
    x.model.fmt.chunk_samples=2048;x.model.reply=NativeWakeResult::none;
    assert(x.native->begin(1000));
    for(int i=1;i<=30;++i)assert(x.native->poll(1000+i*10).step==NativeWakeStep::listening);
    assert(x.model.calls==2 && x.model.frames[0].size()==2048);
  } else if(test=="late_read_stop" || test=="late_read_consent" || test=="late_read_speaker") {
    assert(x.native->begin(1000));
    x.wake_mic.hook=[&]{
      if(test=="late_read_stop")x.stop=true;
      if(test=="late_read_consent")x.consent=false;
      if(test=="late_read_speaker")x.busy=true;
    };
    assert(x.native->poll(1010).step==NativeWakeStep::rejected);
    assert(x.wake_mic.calls==1 && x.model.calls==0 && !x.hardware.mic);
  } else if(test=="late_detect_stop" || test=="late_detect_consent" || test=="late_detect_speaker") {
    x.model.hook=[&]{
      if(test=="late_detect_stop")x.stop=true;
      if(test=="late_detect_consent")x.consent=false;
      if(test=="late_detect_speaker")x.busy=true;
    };
    auto e=x.wake();assert(e.step==NativeWakeStep::rejected && !e.epoch);
    assert(x.session.state()==State::stopped && x.api.calls==0 && !x.hardware.mic);
  } else if(test=="io_failure") {
    assert(x.native->begin(1000));x.wake_mic.fail=true;
    assert(x.native->poll(1010).step==NativeWakeStep::rejected);
    assert(x.model.calls==0 && !x.hardware.mic && x.native->faulted());
  } else if(test=="model_error" || test=="unknown_model_result") {
    x.model.reply=test=="model_error"?NativeWakeResult::error:static_cast<NativeWakeResult>(77);
    auto e=x.wake();assert(e.step==NativeWakeStep::rejected && !e.epoch);
    assert(x.native->faulted() && x.api.calls==0 && !x.hardware.mic);
  } else if(test=="close_failure") {
    x.model.hook=[&]{x.hardware.fail_close=true;};
    auto e=x.wake();assert(e.step==NativeWakeStep::rejected && !e.epoch);
    assert(x.audio.state()==AudioState::fault && x.api.calls==0);
  } else if(test=="reset_failure") {
    x.model.hook=[&]{x.model.reset_ok=false;};
    auto e=x.wake();assert(e.step==NativeWakeStep::rejected && !e.epoch);
    assert(x.api.calls==0 && !x.hardware.mic);
  } else if(test=="format_change") {
    x.model.hook=[&]{x.model.fmt.chunk_samples=512;};
    auto e=x.wake();assert(e.step==NativeWakeStep::rejected && !e.epoch && x.api.calls==0);
  } else if(test=="gap" || test=="clock_rollback") {
    assert(x.native->begin(1000));
    auto e=x.native->poll(test=="gap"?1101:999);
    assert(e.step==NativeWakeStep::rejected && !e.epoch);
    assert(x.wake_mic.calls==0 && x.model.calls==0 && x.native->faulted());
  } else if(test=="resume_between_polls" || test=="resume_in_read" ||
            test=="resume_in_detect" || test=="first_read_format") {
    assert(x.native->begin(1000));
    if(test=="first_read_format") {
      x.wake_mic.hook=[&]{x.model.fmt.channels=2;};
      assert(x.native->poll(1010).step==NativeWakeStep::rejected);
      assert(x.model.calls==0);
    } else {
      assert(x.native->poll(1010).step==NativeWakeStep::listening);
      assert(x.native->poll(1020).step==NativeWakeStep::listening);
      auto resume=[&]{x.session.stop();assert(x.session.resume(1030));};
      if(test=="resume_between_polls")resume();
      if(test=="resume_in_read")x.wake_mic.hook=resume;
      if(test=="resume_in_detect")x.model.hook=resume;
      const auto e=x.native->poll(1030);
      assert(e.step==NativeWakeStep::rejected && !e.epoch);
      assert(x.model.calls==(test=="resume_in_detect"?1:0));
    }
    assert(!x.hardware.mic && x.native->faulted() && x.api.calls==0);
    assert(x.session.state()==State::stopped);
  } else if(test=="inactive_lifetime") {
    auto e=x.wake();assert(e.epoch);
    assert(x.native->cancel().step==NativeWakeStep::inactive);
    x.native.reset();
    assert(x.session.state()==State::ready && x.turn.arm(*e.epoch,1040));
  } else if(test=="active_destruction") {
    assert(x.native->begin(1000));x.native.reset();
    assert(!x.hardware.mic && x.audio.stopped() && x.api.calls==0);
  } else assert(false);
  std::cout<<"native-wake fake-model case PASS; no device/API\n";
}

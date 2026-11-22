// SPDX-License-Identifier: MIT
// Real stream/session/voice pipeline; fake hardware, neural model, API and sink.
#include "native_wake_controller.hpp"
#include "voice_turn_coordinator.hpp"
#include "guarded_voice_speaker.hpp"
#include "native_voice_loop.hpp"
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
  std::function<void()> on_commit;
  ReadValue read(std::string_view k,size_t bound) override {
    if (k!="budget" || budget.empty()) return {ReadCode::missing,{}};
    if (budget.size()>bound) return {ReadCode::failure,{}};
    return {ReadCode::found,budget};
  }
  bool commit(std::string_view k,std::span<const uint8_t> b) override {
    if(k!="budget") { return false; }
    budget.assign(b.begin(),b.end());
    if(on_commit)on_commit();
    return true;
  }
};
struct Hardware {
  bool mic=false,amp=false,fail_close=false;
  int on=0;
  std::function<void()> mic_opening, mic_closing;
  AudioHooks hooks() { return {
    [this]{if(fail_close)return false;if(mic_closing)mic_closing();mic=false;return true;},
    [this]{amp=false;return true;}, []{return true;},
    [this]{++on;if(mic_opening)mic_opening();mic=true;return true;}, []{return true;},
    [this]{amp=true;return true;}, []{return true;}}; }
};
struct Mic:MonoMicReader {
  Hardware& hw; bool question=false,fail=false; int calls=0;
  std::function<void()> hook;
  std::function<int16_t(int)> signal;
  explicit Mic(Hardware& h,bool q=false):hw(h),question(q){}
  bool read_10ms(std::span<int16_t> pcm) override {
    assert(hw.mic && !hw.amp && pcm.size()==240);
    if(hook)hook();
    ++calls; if(fail)return false;
    for(auto& v:pcm)v=signal?signal(calls):question?(calls<=8?2000:0):-7000;
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
  std::function<void(std::span<const int16_t>)> on_question;
  std::function<void(VoiceApiStage)> on_reply;
  explicit Api(Hardware& h):hw(h){}
  VoiceApiReply request(const VoiceApiRequest& r) override {
    assert(!hw.mic && !hw.amp);
    assert(r.dispatch_permit && r.dispatch_permit->consume_once(r.stage,r.session_epoch));
    VoiceApiReply v; v.success=true;v.http_status=200;v.finished_ms=r.started_ms+1;
    if(calls==0){
      assert(r.stage==VoiceApiStage::transcribe);
      if(on_question)on_question(r.pcm24k);
      for(auto sample:r.pcm24k)assert(sample==0 || sample==2000);
      v.utf8_text="질문";
    }
    else if(calls==1){assert(r.stage==VoiceApiStage::respond);v.utf8_text="답변";}
    else {assert(calls==2 && r.stage==VoiceApiStage::synthesize);v.pcm24k.assign(240,1);}
    ++calls;
    if(on_reply)on_reply(r.stage);
    return v;
  }
};
struct Sink:VoiceSpeakerPort {
  Hardware& hw; int calls=0;
  std::function<void()> on_play;
  explicit Sink(Hardware& h):hw(h){}
  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,uint64_t now) override {
    assert(!hw.mic && hw.amp && !pcm.empty());++calls;
    if(on_play)on_play();
    return {true,now+1};
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
  VoiceTurnCoordinator turn{session,ledger,entry,bridge,audio,stop,consent,busy,
                            QuestionCapture::allocate_host_pcm};
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
  constexpr int initial_quiet=QuestionCapture::kInitialQuietFrames;
  if(test=="loop_wake_tail" || test.starts_with("loop_silent_question")) {
    const bool new_question=test=="loop_wake_tail";
    const bool stop_on_close=test=="loop_silent_question_stop";
    const bool fail_close=test=="loop_silent_question_close_fault";
    constexpr int quiet=initial_quiet;
    constexpr int endpoint=QuestionCapture::kEndFrames;
    // An initial wake tail, an almost sufficient quiet run, then one more
    // transient. The question begins only after a full new quiet run.
    constexpr int question_at=4+quiet-1+1+quiet;
    x.question_mic.signal=[=](int read) -> int16_t {
      const int frame=(read-1)/2;
      if(new_question && (frame<4 || frame==4+quiet-1))return 7000;
      return new_question && frame>=question_at && frame<question_at+4?2000:0;
    };
    x.api.on_question=[](std::span<const int16_t> pcm) {
      assert(pcm.size()==4*QuestionCapture::kFrame);
      for(const auto sample:pcm)assert(sample==2000);
    };
    x.session.cloud_enable(true);
    NativeVoiceLoop loop{x.session,x.ledger,*x.native,x.turn,x.audio,x.model,
                         x.stop,x.consent,x.busy,[]{return true;}};
    const auto poll=[&](uint64_t now){return loop.poll(now,1800000000,x.models);};
    assert(poll(1000)==NativeVoiceStep::listening);
    assert(poll(1010)==NativeVoiceStep::listening);
    assert(poll(1020)==NativeVoiceStep::questioning);
    const auto epoch=x.session.epoch();
    const auto budget=x.store.budget;
    if(new_question) {
      for(int frame=0;frame<question_at;++frame) {
        assert(poll(1040+uint64_t(frame)*20)==NativeVoiceStep::questioning);
        assert(x.session.state()==State::ready && !x.turn.has_question_audio());
        assert(x.api.calls==0 && x.store.budget==budget);
      }
      for(int frame=question_at;frame<question_at+4+endpoint-1;++frame)
        assert(poll(1040+uint64_t(frame)*20)==NativeVoiceStep::questioning);
      assert(poll(1040+uint64_t(question_at+4+endpoint-1)*20)==NativeVoiceStep::answered);
      assert(x.api.calls==3 && x.sink.calls==1 && x.ledger.reserved_conversations()==1);
    } else {
      for(uint64_t now=1040;now<6020;now+=20)
        assert(poll(now)==NativeVoiceStep::questioning);
      const auto reads=x.question_mic.calls;
      if(stop_on_close)x.hardware.mic_closing=[&]{x.stop=true;};
      if(fail_close)x.hardware.fail_close=true;
      const auto result=poll(6020);
      assert(x.question_mic.calls==reads);
      assert(x.api.calls==0 && x.sink.calls==0 && x.store.budget==budget);
      assert(!x.turn.active() && !x.turn.has_question_audio());
      assert(!x.ledger.reserve(1800000000,true,true,epoch));
      if(stop_on_close || fail_close) {
        assert(result==NativeVoiceStep::stopped && x.session.state()==State::stopped);
        assert(poll(6520)==NativeVoiceStep::stopped);
        if(fail_close)assert(x.audio.state()==AudioState::fault);
      } else {
        assert(result==NativeVoiceStep::cooldown && x.session.state()==State::cooldown);
        assert(!x.hardware.mic && !x.hardware.amp && x.audio.state()==AudioState::idle);
        assert(poll(6519)==NativeVoiceStep::cooldown);
        assert(poll(6520)==NativeVoiceStep::listening);
        assert(poll(6530)==NativeVoiceStep::listening);
        assert(poll(6540)==NativeVoiceStep::questioning && x.session.epoch()>epoch);
      }
    }
    std::cout<<"PASS "<<test<<'\n';return 0;
  }
  if(test.starts_with("loop_")) {
    x.question_mic.signal=[](int read) -> int16_t {
      const int frame=(read-1)/2;
      return frame>=initial_quiet && frame<initial_quiet+4?2000:0;
    };
  }
  if(test.starts_with("loop_lost_during_")) {
    bool measured_ready=true;
    auto revoke=[&]{measured_ready=false;};
    NativeVoiceLoop loop{x.session,x.ledger,*x.native,x.turn,x.audio,x.model,
                         x.stop,x.consent,x.busy,[&]{return measured_ready;}};
    const auto budget_before=x.store.budget;
    x.session.cloud_enable(true);
    const auto poll=[&](uint64_t now){return loop.poll(now,1800000000,x.models);};
    uint64_t loss_poll=1000;
    int api_calls=0, speaker_calls=0;
    bool reserved=false;
    if(test=="loop_lost_during_wake_open") {
      x.hardware.mic_opening=revoke;
    } else if(test=="loop_lost_during_wake_read") {
      x.wake_mic.hook=revoke;
    } else {
      assert(poll(1000)==NativeVoiceStep::listening);
      assert(poll(1010)==NativeVoiceStep::listening);
      loss_poll=1020;
      if(test=="loop_lost_during_detect") {
        x.model.hook=revoke;
      } else if(test=="loop_lost_during_question_open") {
        x.hardware.mic_opening=revoke;
      } else {
        assert(poll(1020)==NativeVoiceStep::questioning);
        loss_poll=1040;
        if(test=="loop_lost_during_question_read") {
          x.question_mic.hook=revoke;
        } else {
          for(int frame=0;frame<initial_quiet+28;++frame,loss_poll+=20)
            assert(poll(loss_poll)==NativeVoiceStep::questioning);
          if(test=="loop_lost_during_question_close") {
            x.hardware.mic_closing=revoke;
          } else {
            reserved=true;
            if(test=="loop_lost_during_reservation") {
              x.store.on_commit=revoke;
            } else if(test=="loop_lost_during_playback") {
              x.sink.on_play=revoke;
              api_calls=3;
              speaker_calls=1;
            } else {
              const bool during_stt=test=="loop_lost_during_stt";
              assert(during_stt || test=="loop_lost_during_tts");
              const auto target=during_stt?VoiceApiStage::transcribe:VoiceApiStage::synthesize;
              x.api.on_reply=[&,target](VoiceApiStage stage){if(stage==target)revoke();};
              api_calls=during_stt?1:3;
            }
          }
        }
      }
    }
    const auto result=poll(loss_poll);
    assert(!measured_ready);
    assert(x.api.calls==api_calls && x.sink.calls==speaker_calls);
    assert(result==NativeVoiceStep::stopped);
    assert(x.session.state()==State::stopped && x.audio.stopped());
    assert(!x.hardware.mic && !x.hardware.amp && !x.native->active());
    assert(!x.turn.active() && !x.turn.has_question_audio());
    assert(!x.ledger.permit_active());
    assert(x.ledger.reserved_conversations()==(reserved?1u:0u));
    assert((x.store.budget!=budget_before)==reserved);
    if(test=="loop_lost_during_wake_open")assert(x.wake_mic.calls==0);
    if(test=="loop_lost_during_detect")assert(x.hardware.on==1);
    measured_ready=true;
    assert(poll(loss_poll+20)==NativeVoiceStep::stopped);
    std::cout<<"PASS "<<test<<'\n';return 0;
  }
  if(test.starts_with("loop_")) {
    bool measured_ready=true;
    NativeVoiceLoop loop{x.session,x.ledger,*x.native,x.turn,x.audio,x.model,
                         x.stop,x.consent,x.busy,[&]{return measured_ready;}};
    if(test=="loop_no_memory")measured_ready=false;
    if(test=="loop_no_model")x.model.available=false;
    if(test=="loop_no_memory" || test=="loop_no_model") {
      assert(loop.poll(1000,1800000000,x.models)==NativeVoiceStep::stopped);
      assert(x.wake_mic.calls==0 && x.hardware.on==0 && x.api.calls==0);
      measured_ready=true;x.model.available=true;
      assert(loop.poll(1010,1800000000,x.models)==NativeVoiceStep::stopped);
    } else {
      if(test!="loop_cloud_off")x.session.cloud_enable(true);
      assert(loop.poll(1000,1800000000,x.models)==NativeVoiceStep::listening);
      if(test=="loop_stop" || test=="loop_revoke" || test=="loop_memory_lost") {
        if(test=="loop_stop")x.stop=true;
        if(test=="loop_revoke")x.consent=false;
        if(test=="loop_memory_lost")measured_ready=false;
        assert(loop.poll(1010,1800000000,x.models)==NativeVoiceStep::stopped);
        assert(!x.hardware.mic && x.api.calls==0);
      } else {
        assert(loop.poll(1010,1800000000,x.models)==NativeVoiceStep::listening);
        assert(loop.poll(1020,1800000000,x.models)==NativeVoiceStep::questioning);
        assert(!x.native->active() && x.turn.active());
        NativeVoiceStep result{};
        constexpr uint64_t end=1040+(initial_quiet+28)*20;
        for(uint64_t now=1040;now<=end;now+=20)result=loop.poll(now,1800000000,x.models);
        if(test=="loop_cloud_off") {
          assert(result==NativeVoiceStep::stopped && x.api.calls==0);
        } else {
          assert(result==NativeVoiceStep::answered && x.api.calls==3 && x.sink.calls==1);
          assert(loop.poll(end+100,1800000000,x.models)==NativeVoiceStep::cooldown);
          assert(!x.hardware.mic && !x.hardware.amp);
          assert(loop.poll(end+600,1800000000,x.models)==NativeVoiceStep::listening);
          assert(x.hardware.mic && !x.hardware.amp && !x.turn.active());
        }
      }
    }
    assert(!x.ledger.has_profile());
    std::cout<<"PASS "<<test<<'\n';return 0;
  }
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

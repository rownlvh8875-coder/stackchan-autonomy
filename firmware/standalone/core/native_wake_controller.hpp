// SPDX-License-Identifier: MIT
// Bounded wake-only mic ownership ->16k model -> shared ready epoch.
// One owner task serializes begin/poll/cancel; external STOP is atomic.
#pragma once
#include "audio_guard.hpp"
#include "mic_frame_bridge.hpp"
#include "native_wake_port.hpp"
#include "stream_resampler.hpp"
#include "voice_dialog_entry.hpp"
#include <algorithm>
#include <array>
#include <optional>
namespace stackchan::standalone {
enum class NativeWakeStep {inactive,listening,detected,rejected};
struct NativeWakeEvent {
  NativeWakeStep step=NativeWakeStep::inactive;
  std::optional<uint64_t> epoch;
};
class NativeWakeController final {
 public:
  NativeWakeController(Session& session,VoiceDialogEntry& entry,MonoMicReader& mic,
                        AudioGuard& audio,NativeWakePort& model)
      : session_(session),entry_(entry),mic_(mic),audio_(audio),model_(model) {}
  NativeWakeController(const NativeWakeController&)=delete;
  NativeWakeController& operator=(const NativeWakeController&)=delete;
  ~NativeWakeController() {if(active_)(void)fail();else clear();}
  bool begin(uint64_t now_ms) {
    if(active_ || faulted_)return false;
    session_.tick(now_ms);
    if(!entry_.wake_allowed() || !model_.ready() || audio_.state()!=AudioState::idle)
      return false;
    format_=model_.format();
    if(format_.sample_rate_hz!=16000 || format_.channels!=1 ||
       format_.bits_per_sample!=16 || format_.chunk_samples<160 ||
       format_.chunk_samples>chunk_.size()) { (void)fail();return false; }
    clear();
    if(!model_.reset() || !model_unchanged() || !entry_.wake_allowed() ||
       !audio_.capture_begin() || !entry_.wake_allowed()) {
      (void)fail();return false;
    }
    last_poll_=now_ms;active_=true;return true;
  }
  NativeWakeEvent poll(uint64_t now_ms) {
    if(faulted_)return {NativeWakeStep::rejected,{}};
    if(!active_)return {};
    if(now_ms<last_poll_ || now_ms-last_poll_>100)return fail();
    last_poll_=now_ms;session_.tick(now_ms);
    if(!entry_.wake_allowed() || !model_unchanged())return fail();
    Frames frame;
    if(!mic_.read_10ms(frame.input) || !entry_.wake_allowed() ||
       !resampler_.process(frame.input,frame.output))return fail();
    frame.input.fill(0);
    for(const int16_t sample:frame.output) {
      chunk_[used_++]=sample;
      if(used_!=format_.chunk_samples)continue;
      if(!entry_.wake_allowed() || !model_unchanged())return fail();
      const auto result=model_.detect(std::span(chunk_).first(used_));
      chunk_.fill(0);used_=0;
      if(!entry_.wake_allowed() || !model_unchanged())return fail();
      if(result==NativeWakeResult::detected) {
        if(!audio_.capture_end() || !model_.reset() ||
           !entry_.wake_allowed() || !model_unchanged())return fail();
        clear();
        auto epoch=entry_.confirmed_builtin_wake(now_ms,model_unchanged());
        if(!epoch)return fail();
        active_=false;return {NativeWakeStep::detected,epoch};
      }
      if(result!=NativeWakeResult::none)return fail();
    }
    return {NativeWakeStep::listening,{}};
  }
  NativeWakeEvent cancel() {
    if(active_)return fail();
    clear();return {faulted_?NativeWakeStep::rejected:NativeWakeStep::inactive,{}};
  }
  bool active() const {return active_;}
  bool faulted() const {return faulted_;}
 private:
  struct Frames {
    std::array<int16_t,240> input{};
    std::array<int16_t,160> output{};
    ~Frames(){input.fill(0);output.fill(0);}
  };
  bool model_unchanged() const {return model_.ready() && model_.format()==format_;}
  void clear(){resampler_.reset();chunk_.fill(0);used_=0;}
  NativeWakeEvent fail() {
    faulted_=true;active_=false;clear();
    if(model_.ready())(void)model_.reset();
    entry_.cancel_pending_wake();audio_.stop();session_.stop();
    return {NativeWakeStep::rejected,{}};
  }
  Session& session_;VoiceDialogEntry& entry_;MonoMicReader& mic_;
  AudioGuard& audio_;NativeWakePort& model_;
  StreamingPcm24To16 resampler_;
  NativeWakeFormat format_{};
  std::array<int16_t,2048> chunk_{};
  size_t used_=0;
  uint64_t last_poll_=0;
  bool active_=false,faulted_=false;
};
} // namespace stackchan::standalone

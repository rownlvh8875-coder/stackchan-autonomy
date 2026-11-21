// SPDX-License-Identifier: MIT
// Bounded wake-only mic ownership ->16k model -> shared ready epoch.
// One owner task serializes begin/poll/cancel; external STOP is atomic.
#pragma once
#include "audio_guard.hpp"
#include "native_wake_input.hpp"
#include "voice_dialog_entry.hpp"
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
  ~NativeWakeController() {if(active_)(void)fail();}
  bool begin(uint64_t now_ms) {
    if(active_ || faulted_)return false;
    session_.tick(now_ms);
    if(!entry_.wake_allowed() || !model_.ready() || audio_.state()!=AudioState::idle)
      return false;
    listening_epoch_=session_.epoch();
    if(!input_.configure(model_.format()) || !model_.reset() ||
       !input_.matches(model_) || !same_session() ||
       !audio_.capture_begin() || !same_session()) {
      (void)fail();return false;
    }
    last_poll_=now_ms;active_=true;return true;
  }
  NativeWakeEvent poll(uint64_t now_ms) {
    if(faulted_)return {NativeWakeStep::rejected,{}};
    if(!active_)return {};
    if(now_ms<last_poll_ || now_ms-last_poll_>100)return fail();
    last_poll_=now_ms;session_.tick(now_ms);
    const auto result=input_.poll(mic_,model_,[this] {return same_session();});
    if(result==NativeWakeResult::none)return {NativeWakeStep::listening,{}};
    if(result!=NativeWakeResult::detected || !same_session() ||
       !audio_.capture_end() || !model_.reset() ||
       !same_session() || !input_.matches(model_))return fail();
    auto epoch=entry_.confirmed_builtin_wake(now_ms,input_.matches(model_));
    if(!epoch)return fail();
    active_=false;return {NativeWakeStep::detected,epoch};
  }
  NativeWakeEvent cancel() {
    if(active_)return fail();
    input_.clear();return {faulted_?NativeWakeStep::rejected:NativeWakeStep::inactive,{}};
  }
  bool active() const {return active_;}
  bool faulted() const {return faulted_;}
 private:
  bool same_session() const {
    return entry_.wake_allowed() && session_.epoch()==listening_epoch_;
  }
  NativeWakeEvent fail() {
    faulted_=true;active_=false;input_.clear();
    if(model_.ready())(void)model_.reset();
    entry_.cancel_pending_wake();audio_.stop();session_.stop();
    return {NativeWakeStep::rejected,{}};
  }
  Session& session_;VoiceDialogEntry& entry_;MonoMicReader& mic_;
  AudioGuard& audio_;NativeWakePort& model_;
  NativeWakeInput input_;
  uint64_t last_poll_=0,listening_epoch_=0;
  bool active_=false,faulted_=false;
};
} // namespace stackchan::standalone

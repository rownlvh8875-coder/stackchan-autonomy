// SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <string_view>
namespace stackchan::standalone {
// Reader-task confined. Cross-task permission is passed through atomics by app.
class BenchGate {
 public:
  BenchGate(uint32_t nonce,int64_t now):last_(now),deadline_(now+60000) {
    std::snprintf(expected_.data(),expected_.size(),"START %08lX",static_cast<unsigned long>(nonce));
    if(!nonce)state_=State::stopped;
  }
  bool running() const {return state_==State::running;}
  bool stopped() const {return state_==State::stopped;}
  void tick(int64_t now) {
    if(now<last_ || now>deadline_)state_=State::stopped;
    last_=now;
  }
  void feed(char c,int64_t now) {
    tick(now);if(stopped())return;
    if(c=='\n') {
      const std::string_view line{line_.data(),used_};
      if(line=="STOP")state_=State::stopped;
      else if(!running() && line==expected_.data()) {
        state_=State::running;deadline_=now+10000;
      } else state_=State::stopped;
      used_=0;cr_=false;return;
    }
    if(c=='\r' && !cr_) {cr_=true;return;}
    if(cr_ || c<' ' || c>'~' || used_==line_.size()) {
      state_=State::stopped;return;
    }
    line_[used_++]=c;
  }
 private:
  enum class State {waiting,running,stopped};
  State state_=State::waiting;
  std::array<char,32> expected_{},line_{};
  size_t used_=0;
  bool cr_=false;
  int64_t last_,deadline_;
};
}

#include "audio_guard.hpp"
#include <cassert>
#include <iostream>
#include <string>
#include <vector>
using namespace stackchan::standalone;

struct MockAudio {
  std::vector<std::string> calls;
  bool fail_drain = false;
  bool fail_amp = false;
  AudioHooks hooks() {
    return AudioHooks{
        [this]() { calls.push_back("mic_off"); return true; },
        [this]() { calls.push_back("amp_off"); return !fail_amp; },
        [this]() { calls.push_back("init"); return true; },
        [this]() { calls.push_back("mic_on"); return true; },
        [this]() { calls.push_back("flush"); return true; },
        [this]() { calls.push_back("amp_on_low"); return true; },
        [this]() { calls.push_back("drain"); return !fail_drain; },
    };
  }
};

int main() {
  MockAudio hw;
  AudioGuard guard(hw.hooks());
  assert(!guard.initialize(false, true));
  assert(!guard.initialize(true, false));
  assert(hw.calls.empty()); // no hardware touched before checks
  assert(guard.initialize(true, true));
  assert(hw.calls == std::vector<std::string>({"mic_off", "amp_off", "init"}));
  assert(guard.capture_begin());
  assert(!guard.playback_begin());  // never duplex by accident
  assert(guard.capture_end());
  assert(guard.playback_begin());
  assert(!guard.capture_begin());
  assert(guard.playback_end());
  const size_t count = hw.calls.size();
  assert(count >= 2 && hw.calls[count-2] == "drain" && hw.calls[count-1] == "amp_off");
  assert(guard.capture_begin());
  guard.stop();
  assert(guard.stopped() && guard.state() == AudioState::stopped);
  assert(!guard.capture_begin());
  assert(guard.manual_resume() && guard.state() == AudioState::idle);
  assert(guard.playback_begin());
  hw.fail_drain = true;
  assert(!guard.playback_end());
  assert(guard.state() == AudioState::fault);
  assert(!guard.manual_resume() && !guard.capture_begin());

  MockAudio broken;
  broken.fail_amp = true;
  AudioGuard fail(broken.hooks());
  assert(!fail.initialize(true, true) && fail.state() == AudioState::fault);
  assert(!fail.capture_begin());
  std::cout << "audio guard: PASS (mute-first, exclusive mic/amp, drain, STOP, fault)\n";
}

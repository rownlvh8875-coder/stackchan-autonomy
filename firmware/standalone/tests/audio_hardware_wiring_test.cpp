// SPDX-License-Identifier: MIT
// Host-only power/reset/drain evidence gate. No ESP32, GPIO, or I2C.
#include "audio_hardware_wiring.hpp"

#include <atomic>
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

using namespace stackchan::standalone;

struct FakeBoard final : PhysicalAudioEvidence {
  std::vector<std::string>& events;
  bool identity = true, rails = true, reset = true;
  bool mute = true, flush = true, drained = true;
  int mute_calls = 0, drain_calls = 0;
  explicit FakeBoard(std::vector<std::string>& log) : events(log) {}
  bool force_amplifier_mute() override {
    events.push_back("hard_mute");
    ++mute_calls;
    return mute;
  }
  bool exact_board_confirmed() override {
    events.push_back("board_read");
    return identity;
  }
  bool power_rails_confirmed() override {
    events.push_back("rail_read");
    return rails;
  }
  bool amplifier_reset_confirmed() override {
    events.push_back("reset_read");
    return reset;
  }
  bool discard_microphone_dma() override {
    events.push_back("mic_flush");
    return flush;
  }
  bool output_dma_drained_after_last_write() override {
    events.push_back("drain_witness");
    ++drain_calls;
    return drained;
  }
};

struct FakeCodec {
  std::vector<std::string>& events;
  bool ready = false, microphone = false, output = false;
  int prepare_calls = 0, speaker_on_calls = 0, speaker_off_calls = 0;
  explicit FakeCodec(std::vector<std::string>& log) : events(log) {}
  bool prepare(bool owner, bool identity, bool power_reset) {
    ++prepare_calls;
    events.push_back("codec_prepare");
    if (!owner || !identity || !power_reset) return false;
    ready = true;
    return true;
  }
  bool prepared() const { return ready; }
  bool microphone_on() {
    events.push_back("mic_on");
    if (!ready || output) return false;
    microphone = true;
    return true;
  }
  bool microphone_off() {
    events.push_back("mic_off");
    microphone = false;
    return true;
  }
  bool speaker_on_low_volume() {
    events.push_back("speaker_on");
    ++speaker_on_calls;
    if (!ready || microphone) return false;
    output = true;
    return true;
  }
  bool speaker_off() {
    events.push_back("speaker_off");
    ++speaker_off_calls;
    output = false;
    return true;
  }
};

struct Fixture {
  std::vector<std::string> events;
  FakeCodec codec{events};
  FakeBoard board{events};
  std::atomic_bool owner{true}, stop{false};
  AudioGuard guard{bind_verified_audio_hooks(codec, board, owner, stop)};
};

int main() {
  {
    Fixture x;
    assert(!x.guard.initialize(false, true));
    assert(!x.guard.initialize(true, false));
    assert(x.events.empty());
    assert(x.guard.initialize(true, true));
    assert(x.codec.prepare_calls == 1 && x.codec.prepared());
    // Electrical mute before codec mute / prepare, even on first init.
    assert(x.events.at(0) == "mic_off" && x.events.at(1) == "hard_mute");
    assert(x.events.at(2) == "speaker_off");
    assert(x.guard.capture_begin());
    assert(x.codec.microphone);
    assert(!x.guard.playback_begin()); // No duplex allowed.
    assert(x.guard.capture_end());
    assert(x.guard.playback_begin());
    assert(x.codec.output && !x.codec.microphone);
    assert(x.guard.playback_end());
    assert(x.board.drain_calls == 1 && x.guard.state() == AudioState::idle);
    assert(!x.codec.output);
    const auto n = x.events.size();
    assert(n >= 3 && x.events[n-3] == "drain_witness");
    assert(x.events[n-2] == "hard_mute" && x.events[n-1] == "speaker_off");
  }
  {
    Fixture x;
    x.board.identity = false;
    assert(!x.guard.initialize(true, true));
    assert(x.codec.prepare_calls == 0);
    assert(x.guard.state() == AudioState::fault);
  }
  {
    Fixture x;
    x.board.rails = false;
    assert(!x.guard.initialize(true, true));
    assert(x.codec.prepare_calls == 0);
  }
  {
    Fixture x;
    x.board.reset = false;
    assert(!x.guard.initialize(true, true));
    assert(x.codec.prepare_calls == 0);
  }
  {
    Fixture x;
    x.owner.store(false);
    assert(!x.guard.initialize(true, true));
    assert(x.codec.prepare_calls == 0);
  }
  {
    Fixture x;
    x.board.mute = false;
    assert(!x.guard.initialize(true, true));
    assert(x.codec.speaker_off_calls >= 1);
    assert(x.guard.state() == AudioState::fault);
  }
  {
    Fixture x;
    assert(x.guard.initialize(true, true));
    assert(x.guard.capture_begin());
    assert(x.guard.capture_end());
    x.board.rails = false;
    assert(!x.guard.playback_begin());
    assert(x.codec.speaker_on_calls == 0);
    assert(x.guard.state() == AudioState::fault);
  }
  {
    Fixture x;
    assert(x.guard.initialize(true, true));
    assert(x.guard.playback_begin());
    x.board.drained = false; // Queued output is not proof of played output.
    assert(!x.guard.playback_end());
    assert(!x.codec.output && x.guard.state() == AudioState::fault);
    x.guard.stop();
    assert(x.guard.state() == AudioState::fault);
    assert(!x.guard.manual_resume());
  }
  {
    Fixture x;
    assert(x.guard.initialize(true, true));
    assert(x.guard.playback_begin());
    x.stop.store(true);
    x.guard.stop(); // Independent physical STOP service.
    assert(!x.codec.output && x.guard.stopped());
    assert(!x.guard.playback_end());
  }
  {
    Fixture x;
    assert(x.guard.initialize(true, true));
    x.board.flush = false;
    assert(!x.guard.capture_begin());
    assert(x.guard.state() == AudioState::fault);
  }
  std::cout << "physical audio evidence contract: PASS (fake hardware only)\n";
}

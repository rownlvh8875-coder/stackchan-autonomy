// SPDX-License-Identifier: MIT
// Playback lifecycle safety checks; no real codec, network or secrets.
#include "guarded_voice_speaker.hpp"

#include <atomic>
#include <cassert>
#include <iostream>
#include <vector>

using namespace stackchan::standalone;

struct AudioFake {
  bool microphone = false, amplifier = false;
  bool fail_drain = false;
  int drain_calls = 0, speaker_on_calls = 0;
  AudioHooks hooks() {
    return {
        [this]() { microphone = false; return true; },
        [this]() { amplifier = false; return true; },
        []() { return true; },
        [this]() { microphone = true; return true; },
        []() { return true; },
        [this]() { ++speaker_on_calls; amplifier = true; return true; },
        [this]() { ++drain_calls; return !fail_drain; }
    };
  }
};

struct PcmFake final : VoiceSpeakerPort {
  AudioFake& hardware;
  AudioGuard& guard;
  std::atomic_bool& busy;
  std::atomic_bool& stop;
  int calls = 0;
  bool fail = false, set_stop = false, invalid_time = false;

  PcmFake(AudioFake& h, AudioGuard& g, std::atomic_bool& b,
          std::atomic_bool& s) : hardware(h), guard(g), busy(b), stop(s) {}

  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,
                                  uint64_t now) override {
    assert(!hardware.microphone && hardware.amplifier);
    assert(guard.state() == AudioState::playback && busy.load());
    assert(!pcm.empty());
    assert(!guard.capture_begin()); // Mic+amp duplex forbidden.
    ++calls;
    if (set_stop) stop.store(true);
    return {!fail, invalid_time ? now - 1 : now + 10};
  }
};

struct Fixture {
  AudioFake hardware;
  std::atomic_bool stop{false}, consent{true}, busy{false};
  AudioGuard guard{hardware.hooks()};
  PcmFake sink{hardware, guard, busy, stop};
  GuardedVoiceSpeaker speaker{guard, sink, stop, consent, busy};
  std::vector<int16_t> samples{1, 2, 3};
  Fixture() { assert(guard.initialize(true, true)); }
};

int main() {
  {
    Fixture x;
    assert(x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.sink.calls == 1 && x.hardware.drain_calls == 1);
    assert(x.guard.state() == AudioState::idle);
    assert(!x.busy.load() && !x.hardware.amplifier);
    assert(x.speaker.play_pcm24k({}, 1300).complete == false);
    assert(x.sink.calls == 1 && !x.speaker.latched());
  }
  {
    Fixture x;
    assert(x.guard.capture_begin());
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.sink.calls == 0 && !x.hardware.amplifier);
    assert(x.guard.capture_end());
  }
  {
    Fixture x;
    x.busy.store(true); // Another speaker already owns output.
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.sink.calls == 0 && x.guard.state() == AudioState::idle);
  }
  {
    Fixture x;
    x.sink.fail = true;
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.sink.calls == 1 && x.speaker.latched() && x.busy.load());
    assert(x.guard.state() == AudioState::stopped && !x.hardware.amplifier);
    assert(!x.speaker.play_pcm24k(x.samples, 1210).complete);
    assert(x.sink.calls == 1);
  }
  {
    Fixture x;
    x.sink.set_stop = true; // STOP during synchronous output.
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.stop.load() && x.speaker.latched() && !x.hardware.amplifier);
  }
  {
    Fixture x;
    x.sink.invalid_time = true;
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.speaker.latched() && x.guard.stopped());
  }
  {
    Fixture x;
    x.hardware.fail_drain = true;
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.hardware.drain_calls == 1 && x.speaker.latched());
    assert(x.guard.state() == AudioState::fault && !x.hardware.amplifier);
  }
  {
    Fixture x;
    x.stop.store(true);
    assert(!x.speaker.play_pcm24k(x.samples, 1200).complete);
    assert(x.sink.calls == 0 && !x.hardware.amplifier);
  }
  std::cout << "guarded speaker: PASS (host fake only)\n";
}

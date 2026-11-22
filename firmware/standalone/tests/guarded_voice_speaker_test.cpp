// SPDX-License-Identifier: MIT
// Playback lifecycle safety checks; no real codec, network or secrets.
#include "guarded_voice_speaker.hpp"
#include "pcm_chunk_guard.hpp"

#include <array>
#include <atomic>
#include <cassert>
#include <iostream>
#include <vector>

using namespace stackchan::standalone;

struct AudioFake {
  bool microphone = false, amplifier = false;
  bool fail_drain = false, fail_mute = false;
  int drain_calls = 0, speaker_on_calls = 0;
  AudioHooks hooks() {
    return {
        [this]() { microphone = false; return true; },
        [this]() { amplifier = false; return !fail_mute; },
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
  std::atomic_bool& consent;
  int calls = 0, blocks = 0;
  bool use_bounded_stream = false;
  bool fail = false, set_stop = false, invalid_time = false;

  PcmFake(AudioFake& h, AudioGuard& g, std::atomic_bool& b,
          std::atomic_bool& s, std::atomic_bool& c)
      : hardware(h), guard(g), busy(b), stop(s), consent(c) {}

  VoicePlaybackResult play_pcm24k(std::span<const int16_t> pcm,
                                  uint64_t now) override {
    assert(!hardware.microphone && hardware.amplifier);
    assert(guard.state() == AudioState::playback && busy.load());
    assert(!pcm.empty());
    assert(!guard.capture_begin()); // Mic+amp duplex forbidden.
    ++calls;
    if (use_bounded_stream) {
      auto finished = stream_pcm_chunks_guarded(
          pcm, now, stop, consent,
          [&](std::span<const int16_t> chunk) {
            assert(chunk.size() == 240 && hardware.amplifier && !hardware.microphone);
            assert(std::ranges::min(chunk) == -256 && std::ranges::max(chunk) == 256);
            ++blocks;
            now += 10;
            if (set_stop) stop.store(true);
            return true;
          },
          [&] { return std::optional{now}; });
      if (!finished) return {};
      return {true, *finished};
    }
    if (set_stop) stop.store(true);
    return {!fail, invalid_time ? now - 1 : now + 10};
  }
};

struct Fixture {
  AudioFake hardware;
  std::atomic_bool stop{false}, consent{true}, busy{false};
  AudioGuard guard{hardware.hooks()};
  PcmFake sink{hardware, guard, busy, stop, consent};
  GuardedVoiceSpeaker speaker{guard, sink, stop, consent, busy};
  std::vector<int16_t> samples{1, 2, 3};
  Fixture() { assert(guard.initialize(true, true)); }
};

int main() {
  for (int test = 0; test < 5; ++test) {
    Fixture x;
    x.hardware.fail_mute = test == 4;
    int clock_reads = 0;
    GuardedVoiceSpeaker speaker{
        x.guard, x.sink, x.stop, x.consent, x.busy,
        [&]() -> std::optional<uint64_t> {
          ++clock_reads;
          assert(!x.hardware.amplifier && x.busy && x.guard.state() == AudioState::idle);
          if (test == 1) return std::nullopt;
          if (test == 2) return 1209; // Earlier than the sink's 1210.
          if (test == 3) x.stop = true;
          return 1235;
        }};
    const auto result = speaker.play_pcm24k(x.samples, 1200);
    assert(clock_reads == (test == 4 ? 0 : 1));
    if (test == 0) {
      assert(result.complete && result.finished_ms == 1235 && !x.busy);
    } else {
      assert(!result.complete && speaker.latched() && x.busy && x.guard.stopped());
    }
  }
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
  // A non-voice signal traverses the same bounded PCM and playback guard.
  constexpr std::array<int16_t, 8> period{0, 128, 256, 128, 0, -128, -256, -128};
  std::array<int16_t, 480> test_tone{};
  for (size_t i = 0; i < test_tone.size(); ++i) test_tone[i] = period[i % period.size()];
  for (const bool stop_after_first : {false, true}) {
    Fixture x;
    x.sink.use_bounded_stream = true;
    x.sink.set_stop = stop_after_first;
    const auto playback = x.speaker.play_pcm24k(test_tone, 1200);
    assert(x.sink.blocks == (stop_after_first ? 1 : 2));
    assert(playback.complete == !stop_after_first && !x.hardware.amplifier);
    if (stop_after_first) {
      assert(x.guard.stopped() && x.speaker.latched() && x.hardware.drain_calls == 0);
    } else {
      assert(playback.finished_ms == 1220 && x.guard.state() == AudioState::idle);
      assert(x.hardware.drain_calls == 1 && !x.busy.load());
    }
  }
  std::cout << "guarded speaker: PASS (host fake only)\n";
}

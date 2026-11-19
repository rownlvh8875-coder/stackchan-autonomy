// SPDX-License-Identifier: MIT
#include "mic_frame_bridge.hpp"
#include <array>
#include <atomic>
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

struct FakeMic final : MonoMicReader {
  int calls = 0;
  int fail_on = -1;
  int stop_on = -1;
  int voiced_reads = 6;
  std::atomic_bool* stop = nullptr;
  bool read_10ms(std::span<int16_t> pcm) override {
    assert(pcm.size() == 240);
    const int index = calls++;
    if (stop && index == stop_on) stop->store(true);
    if (index == fail_on) return false;
    for (auto& sample : pcm) sample = index < voiced_reads ? 2000 : 0;
    return true;
  }
};

int main() {
  {
    std::atomic_bool stop{false}, playback{false};
    FakeMic mic;
    MicFrameBridge bridge(mic, stop, playback);
    QuestionCapture capture;
    for (int i = 0; i < 3; ++i)
      assert(bridge.capture(capture) == (i == 2 ? CaptureResult::speech_started : CaptureResult::listening));
    for (int i = 0; i < 24; ++i)
      assert(bridge.capture(capture) == CaptureResult::speech_started);
    assert(bridge.capture(capture) == CaptureResult::ready);
    assert(capture.audio().size() == 3 * QuestionCapture::kFrame);
    assert(!bridge.faulted());
    // Even an already-ready question must be discarded after STOP.
    stop.store(true);
    assert(bridge.capture(capture) == CaptureResult::rejected);
    assert(capture.audio().empty() && bridge.faulted());
  }
  {
    std::atomic_bool stop{false}, playback{false};
    FakeMic mic;
    mic.fail_on = 1; // Half of a 20ms frame was received.
    MicFrameBridge bridge(mic, stop, playback);
    QuestionCapture capture;
    assert(bridge.capture(capture) == CaptureResult::rejected);
    assert(bridge.faulted() && capture.audio().empty());
    assert(bridge.capture(capture) == CaptureResult::rejected);
    assert(mic.calls == 2); // Fault is latched, never retried.
  }
  {
    std::atomic_bool stop{false}, playback{false};
    FakeMic mic;
    mic.stop = &stop;
    mic.stop_on = 0;
    MicFrameBridge bridge(mic, stop, playback);
    QuestionCapture capture;
    assert(bridge.capture(capture) == CaptureResult::rejected);
    assert(mic.calls == 1 && capture.audio().empty());
  }
  {
    std::atomic_bool stop{false}, playback{true};
    FakeMic mic;
    MicFrameBridge bridge(mic, stop, playback);
    QuestionCapture capture;
    assert(bridge.capture(capture) == CaptureResult::rejected);
    assert(mic.calls == 0);
  }
  std::cout << "mic frame bridge PASS (fake 10ms reads only)\n";
}

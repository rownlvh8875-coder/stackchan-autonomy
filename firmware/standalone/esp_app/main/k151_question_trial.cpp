// SPDX-License-Identifier: MIT
#include "k151_question_trial.hpp"
#include "k151_mic_reader.hpp"
#include "k151_question_pcm.hpp"
#include "mic_frame_bridge.hpp"
#include <esp_timer.h>
#include <cstdint>

namespace stackchan::standalone {
namespace {
using QuestionResult = K151QuestionTrialResult;
constexpr int64_t kQuestionWindowUs = QuestionCapture::kMaxFrames * 20'000;

template<class Allowed>
QuestionResult record_question(K151CodecPort& codec, QuestionCapture& capture,
                               const Allowed& allowed, void (*cue)(),
                               const std::atomic_bool& stop, K151QuestionTrialMode mode) {
  auto previous_us = esp_timer_get_time();
  if (previous_us < 0) return QuestionResult::clock_fault;
  const auto started_us = previous_us;
  const auto clock = [&] {
    const auto now = esp_timer_get_time();
    if (now < previous_us) return int64_t{-1};
    previous_us = now;
    return now;
  };
  const std::atomic_bool speaker_busy{false}; // Receive-only port owns no TX.
  K151MicReader mic{codec};
  MicFrameBridge bridge{mic, stop, speaker_busy};
  const bool wake_only = mode == K151QuestionTrialMode::wake_only_control;
  bool cued = false;
  size_t observed_frames = 0;
  for (size_t frame = 0; frame < QuestionCapture::kMaxFrames; ++frame) {
    if (!allowed()) return QuestionResult::stopped;
    const auto before = clock();
    if (before < 0) return QuestionResult::clock_fault;
    if (before - started_us >= kQuestionWindowUs) break;
    const auto progress = bridge.capture(capture);
    if (!allowed()) return QuestionResult::stopped;
    const auto after = clock();
    if (after < 0) return QuestionResult::clock_fault;
    if (progress == CaptureResult::rejected) return QuestionResult::read_failed;
    if (after - started_us > kQuestionWindowUs) break;
    if (progress == CaptureResult::ready) return QuestionResult::endpoint;
    if (cued) {
      if (wake_only && ++observed_frames == kK151WakeOnlyObservationFrames)
        return QuestionResult::no_endpoint;
    } else if (progress == CaptureResult::listening) {
      if (frame + 1 == QuestionCapture::kMaxFrames || after - started_us == kQuestionWindowUs)
        break;
      if (!allowed()) return QuestionResult::stopped;
      cue();
      cued = true;
    }
  }
  if (!cued) return QuestionResult::quiet_timeout;
  // A wake-only control must observe the whole short window to complete.
  return wake_only ? QuestionResult::stopped : QuestionResult::no_endpoint;
}

}  // namespace

K151QuestionTrialDiagnostic run_k151_question_trial(
    const std::atomic_bool& owner, const std::atomic_bool& stop,
    const K151MicOnlyEvidence& evidence, void (*cue)(), K151QuestionTrialMode mode) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (!allowed()) return {QuestionResult::stopped};
  if (!evidence.verified() || !cue) return {QuestionResult::prepare_failed};
  QuestionCapture capture{QuestionCapture::kDefaultMinRms, k151_allocate_question_pcm,
                          QuestionCapture::Start::after_quiet};
  const bool memory_available = capture.prepare();
  if (!allowed()) return {QuestionResult::stopped};
  if (!memory_available) return {QuestionResult::memory_denied};

  // A fresh receive-only channel cannot supply buffered WakeNet input. Verify
  // the same board registers and assert amp reset before opening the new RX.
  K151CodecPort codec;
  auto result = QuestionResult::prepare_failed;
  if (codec.prepare_microphone_only(owner, stop, evidence) && allowed()) {
    result = QuestionResult::open_failed;
    if (codec.microphone_on() && allowed()) {
      result = record_question(codec, capture, allowed, cue, stop, mode);
    }
  }
  capture.reset(); // Wipe all question PCM before returning any diagnostics.
  const bool released = codec.shutdown();
  const bool cleanup_unverified = codec.cleanup_unverified();
  if (!allowed() && !cleanup_unverified) result = QuestionResult::stopped;
  const bool completed = result == QuestionResult::endpoint ||
                         result == QuestionResult::no_endpoint ||
                         result == QuestionResult::quiet_timeout;
  if ((!released && completed) || (cleanup_unverified && result == QuestionResult::stopped)) {
    result = QuestionResult::release_failed;
  }
  return {result, cleanup_unverified};
}

}  // namespace stackchan::standalone

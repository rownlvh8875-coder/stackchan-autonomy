// SPDX-License-Identifier: MIT
#include "k151_mic_wake_trial.hpp"
#include "k151_mic_wake_memory.hpp"
#include "k151_mic_reader.hpp"
#include "k151_question_pcm.hpp"
#include "pcm_frame.hpp"
#include <esp_timer.h>
#include <cstdio>
#include <limits>
#include <utility>

namespace stackchan::standalone {
namespace {
using Result = K151MicWakeTrialResult;
using Stage = K151MicWakeStage;
constexpr int64_t kCaptureWindowUs = 5'000'000;
constexpr int64_t kMaxPollGapUs = 100'000;

const char* result_name(Result result) {
  switch (result) {
    case Result::denied: return "denied";
    case Result::stopped: return "stopped";
    case Result::not_detected: return "not_detected";
    case Result::detected: return "detected";
    case Result::fault: return "fault";
    case Result::memory_denied: return "memory_denied";
  }
  return nullptr;
}

const char* stage_name(Stage stage) {
  switch (stage) {
    case Stage::admission: return "admission";
    case Stage::baseline_memory: return "baseline_memory";
    case Stage::model_prepare: return "model_prepare";
    case Stage::input_format: return "input_format";
    case Stage::model_reset: return "model_reset";
    case Stage::resident_memory: return "resident_memory";
    case Stage::i2c_bus: return "i2c_bus";
    case Stage::board_power: return "board_power";
    case Stage::amplifier_reset: return "amplifier_reset";
    case Stage::board_release: return "board_release";
    case Stage::i2s_rx: return "i2s_rx";
    case Stage::codec_prepare: return "codec_prepare";
    case Stage::codec_open: return "codec_open";
    case Stage::capture_clock: return "capture_clock";
    case Stage::capture_read: return "capture_read";
    case Stage::wake_input: return "wake_input";
    case Stage::codec_release: return "codec_release";
    case Stage::complete: return "complete";
  }
  return nullptr;
}

bool diagnostic_matches(Result result, K151MicWakeDiagnostic diagnostic) {
  const auto stage = diagnostic.stage;
  const bool cleanup = diagnostic.codec_cleanup_unverified;
  const bool memory = stage == Stage::baseline_memory || stage == Stage::resident_memory;
  switch (result) {
    case Result::detected:
    case Result::not_detected: return stage == Stage::complete && !cleanup;
    case Result::denied: return stage == Stage::admission && !cleanup;
    case Result::stopped: return stage != Stage::complete && !cleanup;
    case Result::memory_denied: return memory && !cleanup;
    case Result::fault:
      return stage != Stage::admission && stage != Stage::complete && !memory &&
             (!cleanup || (stage != Stage::model_prepare && stage != Stage::model_reset)) &&
             (stage != Stage::codec_release || cleanup);
  }
  return false;
}

class CountedMicReader final : public MonoMicReader {
 public:
  explicit CountedMicReader(K151CodecPort& codec) : mic_(codec) {}

  bool read_10ms(std::span<int16_t> pcm) override {
    if (!mic_.read_10ms(pcm)) {
      read_failed_ = true;
      return false;
    }
    bool all_zero = true;
    for (const int16_t sample : pcm) {
      all_zero &= sample == 0;
      counts_.full_scale_samples += sample == std::numeric_limits<int16_t>::min() ||
                                    sample == std::numeric_limits<int16_t>::max();
    }
    ++counts_.frames_read;
    counts_.all_zero_frames += all_zero;
    return true;
  }

  K151MicWakeInputCounts counts() const { return counts_; }
  bool read_failed() const { return read_failed_; }

 private:
  K151MicReader mic_;
  K151MicWakeInputCounts counts_;
  bool read_failed_ = false;
};

template<class Allowed>
Result listen(NativeWakeInput& input, CountedMicReader& mic, NativeWakePort& model,
              int64_t start_us, const Allowed& allowed, Stage& stage) {
  stage = Stage::wake_input;
  auto last_poll_us = start_us;
  auto last_clock_us = start_us;
  const auto clock = [&] {
    const auto now = esp_timer_get_time();
    if (now < last_clock_us) return int64_t{-1};
    last_clock_us = now;
    return now;
  };

  for (unsigned frame = 0; frame < kK151MicWakeTrialFrameLimit; ++frame) {
    if (!allowed()) return Result::stopped;
    const auto before = clock();
    if (before < 0 || before - last_poll_us > kMaxPollGapUs) {
      stage = Stage::capture_clock;
      return Result::fault;
    }
    if (before - start_us >= kCaptureWindowUs) break;
    last_poll_us = before;
    const auto within_time = [&] {
      const auto now = clock();
      return now >= 0 && now - before <= kMaxPollGapUs &&
             now - start_us <= kCaptureWindowUs;
    };
    const auto result = input.poll(mic, model, [&] { return within_time() && allowed(); });
    if (!within_time()) {
      stage = Stage::capture_clock;
      return Result::fault;
    }
    if (mic.read_failed()) stage = Stage::capture_read;
    if (!allowed()) return Result::stopped;
    if (result == NativeWakeResult::error) return Result::fault;
    if (result == NativeWakeResult::detected) return Result::detected;
  }
  return Result::not_detected;
}

using QuestionResult = K151QuestionTrialResult;
constexpr int64_t kQuestionWindowUs = QuestionCapture::kMaxFrames * 20'000;

template<class Allowed>
QuestionResult record_question(K151CodecPort& codec, QuestionCapture& capture,
                               const Allowed& allowed, K151MicWakeTrial::ListenStarted cue,
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

K151QuestionTrialDiagnostic capture_question(const std::atomic_bool& owner,
                                              const std::atomic_bool& stop,
                                              const K151MicOnlyEvidence& evidence,
                                              K151MicWakeTrial::ListenStarted cue,
                                              K151QuestionTrialMode mode) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (!allowed()) return {QuestionResult::stopped};
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
}  // namespace

size_t format_k151_mic_wake_report(K151MicWakeTrialResult result,
                                 K151MicWakeDiagnostic diagnostic,
                                 std::optional<K151MicWakeInputCounts> counts,
                                 std::span<char> output) {
  if (output.empty()) return 0;
  output.front() = '\0';
  const char* name = result_name(result);
  const char* stage = stage_name(diagnostic.stage);
  const bool clean = result == Result::detected || result == Result::not_detected;
  if (!name || !stage || !diagnostic_matches(result, diagnostic) ||
      clean != counts.has_value()) return 0;
  if (counts &&
      (counts->frames_read == 0 || counts->frames_read > kK151MicWakeTrialFrameLimit ||
       counts->all_zero_frames > counts->frames_read ||
       counts->full_scale_samples >
           (counts->frames_read - counts->all_zero_frames) * kPcmFramesPerTenMs)) return 0;

  const int prefix = std::snprintf(output.data(), output.size(),
      "{\"mic_wake_trial\":\"MIC_WAKE_TRIAL_V2\",\"result\":\"%s\","
      "\"operating_admission\":false,\"stage\":\"%s\",\"codec_cleanup_unverified\":%s",
      name, stage, diagnostic.codec_cleanup_unverified ? "true" : "false");
  if (prefix > 0 && static_cast<size_t>(prefix) < output.size()) {
    const auto tail = output.subspan(static_cast<size_t>(prefix));
    const int suffix = counts ?
        std::snprintf(tail.data(), tail.size(),
                      ",\"frames_read\":%u,\"all_zero_frames\":%u,\"full_scale_samples\":%u}\n",
                      static_cast<unsigned>(counts->frames_read),
                      static_cast<unsigned>(counts->all_zero_frames),
                      static_cast<unsigned>(counts->full_scale_samples)) :
        std::snprintf(tail.data(), tail.size(), "}\n");
    if (suffix > 0 && static_cast<size_t>(suffix) < tail.size()) return prefix + suffix;
  }
  output.front() = '\0';
  return 0;
}

std::optional<K151MicWakeInputCounts> K151MicWakeTrial::take_input_counts() {
  return std::exchange(input_counts_, std::nullopt);
}

K151MicWakeTrialResult K151MicWakeTrial::run(const std::atomic_bool& owner,
                                           const std::atomic_bool& stop,
                                           const K151MicOnlyEvidence& evidence,
                                           std::unique_ptr<NativeWakePort> model) {
  if (const auto denied = begin(owner, stop, evidence)) return *denied;
  return run_prepared(owner, stop, evidence, std::move(model));
}

K151MicWakeTrialResult K151MicWakeTrial::run_prepared(const std::atomic_bool& owner,
                                                     const std::atomic_bool& stop,
                                                     const K151MicOnlyEvidence& evidence,
                                                     std::unique_ptr<NativeWakePort> model) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (!allowed()) return Result::stopped;
  diagnostic_.stage = Stage::input_format;
  if (!model || !model->ready() || !input_.configure(model->format())) return Result::fault;
  if (!allowed()) return Result::stopped;
  diagnostic_.stage = Stage::model_reset;
  if (!model->reset() || !input_.matches(*model)) return Result::fault;
  if (!allowed()) return Result::stopped;
  diagnostic_.stage = Stage::resident_memory;
  const bool resident_headroom = k151_mic_wake_internal_heap_available();
  if (!resident_headroom || !allowed()) {
    model.reset();
    return allowed() ? Result::memory_denied : Result::stopped;
  }

  K151CodecPort codec;
  CountedMicReader mic{codec};
  const bool prepared = codec.prepare_microphone_only(owner, stop, evidence);
  diagnostic_.stage = codec.prepare_stage();
  auto result = allowed() ? Result::fault : Result::stopped;
  if (prepared && allowed()) {
    diagnostic_.stage = Stage::input_format;
    if (input_.matches(*model)) {
      diagnostic_.stage = Stage::capture_clock;
      const auto start_us = esp_timer_get_time();
      if (start_us >= 0) {
        diagnostic_.stage = Stage::codec_open;
        if (codec.microphone_on()) {
          if (allowed() && on_listen_) on_listen_();
          result = listen(input_, mic, *model, start_us, allowed, diagnostic_.stage);
        }
      }
    }
  }
  const bool clean = result == Result::detected || result == Result::not_detected;
  if (clean) diagnostic_.stage = Stage::codec_release;
  input_.clear();
  const bool codec_released = codec.shutdown();
  diagnostic_.codec_cleanup_unverified = codec.cleanup_unverified();
  model.reset();
  if (!codec_released || result == Result::fault) return Result::fault;
  if (!allowed() || result == Result::stopped) return Result::stopped;
  if (clean) {
    diagnostic_.stage = Stage::complete;
    input_counts_ = mic.counts();
  }
  if (result == Result::detected && on_question_)
    question_diagnostic_ = capture_question(owner, stop, evidence, on_question_, question_mode_);
  return result;
}

}  // namespace stackchan::standalone

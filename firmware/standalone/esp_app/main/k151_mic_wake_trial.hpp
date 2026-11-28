// SPDX-License-Identifier: MIT
#pragma once

#include "k151_question_trial.hpp"
#include "native_wake_input.hpp"
#include <atomic>
#include <memory>
#include <optional>
#include <span>

namespace stackchan::standalone {

enum class K151MicWakeTrialResult { denied, stopped, not_detected, detected, fault, memory_denied };
inline constexpr uint32_t kK151MicWakeTrialFrameLimit = 500;
inline constexpr size_t kK151MicWakeReportBytes = 384;

struct K151MicWakeInputCounts {
  uint32_t frames_read = 0;
  uint32_t all_zero_frames = 0;
  uint32_t full_scale_samples = 0;
};

enum class K151MicWakeClockReason {
  none, invalid_start, clock_rollback, poll_gap_exceeded, poll_duration_exceeded,
  capture_window_exceeded,
};

struct K151WakeDeadlineProgress {
  uint32_t frames_read;
  NativeWakePollTrace poll;
};

struct K151MicWakeDiagnostic {
  K151MicWakeStage stage = K151MicWakeStage::admission;
  // This is independent of the primary failure. A prior fault alone does
  // not make a later successful teardown unverified.
  bool codec_cleanup_unverified = false;
  K151MicWakeClockReason clock_reason = K151MicWakeClockReason::none;
  std::optional<K151WakeDeadlineProgress> deadline_progress{};
};

// Fixed diagnostic JSON line. Returns zero and clears the first byte on
// invalid input or truncation. The caller owns the output buffer.
size_t format_k151_mic_wake_report(K151MicWakeTrialResult result,
                                 K151MicWakeDiagnostic diagnostic,
                                 std::optional<K151MicWakeInputCounts> counts,
                                 std::span<char> output);

// Dormant diagnostic, one synchronous run per instance across both entry points.
// Keep the input buffer off small task stacks. STOP and ownership loss must latch
// through teardown. No PCM leaves the trial.
class K151MicWakeTrial final {
 public:
  static const char* compiled_link_marker();
  using ListenStarted = void (*)();
  // A question cue opts into a distinct receive-only question capture after wake.
  explicit K151MicWakeTrial(ListenStarted on_listen = nullptr,
                           ListenStarted on_question = nullptr,
                           K151QuestionTrialMode question_mode = K151QuestionTrialMode::standard)
      : on_listen_(on_listen), on_question_(on_question), question_mode_(question_mode) {}

  // The local owner supplies current board/I2S ownership evidence and the
  // whole linked model pack. The codec checks live board registers separately.
  K151MicWakeTrialResult run_embedded(const std::atomic_bool& owner, const std::atomic_bool& stop,
                                     const K151MicOnlyEvidence& evidence,
                                     std::span<const uint8_t> pack);

  // Adapter boundary for a preverified exclusive model or a host test double.
  // Passing ownership consumes the model even when the trial is denied.
  K151MicWakeTrialResult run(const std::atomic_bool& owner, const std::atomic_bool& stop,
                            const K151MicOnlyEvidence& evidence,
                            std::unique_ptr<NativeWakePort> model);

  // Whole-trial counts are available once after clean detected/not_detected
  // completion. An attempt that stops, faults or is denied leaves no counts.
  std::optional<K151MicWakeInputCounts> take_input_counts();
  K151MicWakeDiagnostic diagnostic() const { return diagnostic_; }
  K151QuestionTrialDiagnostic question_diagnostic() const { return question_diagnostic_; }

 private:
  std::optional<K151MicWakeTrialResult> begin(const std::atomic_bool& owner,
                                             const std::atomic_bool& stop,
                                             const K151MicOnlyEvidence& evidence) {
    input_counts_.reset();
    diagnostic_ = {};
    question_diagnostic_ = {};
    if (attempted_) return K151MicWakeTrialResult::denied;
    attempted_ = true;
    if (stop.load()) return K151MicWakeTrialResult::stopped;
    if (!owner.load() || !evidence.verified()) return K151MicWakeTrialResult::denied;
    return std::nullopt;
  }
  K151MicWakeTrialResult run_prepared(const std::atomic_bool& owner, const std::atomic_bool& stop,
                                     const K151MicOnlyEvidence& evidence,
                                     std::unique_ptr<NativeWakePort> model);

  NativeWakeInput input_;
  std::optional<K151MicWakeInputCounts> input_counts_;
  K151MicWakeDiagnostic diagnostic_;
  K151QuestionTrialDiagnostic question_diagnostic_;
  ListenStarted on_listen_;
  ListenStarted on_question_;
  K151QuestionTrialMode question_mode_;
  bool attempted_ = false;
};

}  // namespace stackchan::standalone

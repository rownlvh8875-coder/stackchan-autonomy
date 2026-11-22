// SPDX-License-Identifier: MIT
#pragma once

#include "k151_mic_only_evidence.hpp"
#include "native_wake_input.hpp"
#include <atomic>
#include <memory>
#include <optional>
#include <span>

namespace stackchan::standalone {

enum class K151MicWakeTrialResult { denied, stopped, not_detected, detected, fault, memory_denied };
inline constexpr uint32_t kK151MicWakeTrialFrameLimit = 500;

struct K151MicWakeInputCounts {
  uint32_t frames_read = 0;
  uint32_t all_zero_frames = 0;
  uint32_t full_scale_samples = 0;
};

// Fixed diagnostic JSON line. Returns zero and clears the first byte on
// invalid input or truncation. The caller owns the output buffer.
size_t format_k151_mic_wake_report(K151MicWakeTrialResult result,
                                 std::optional<K151MicWakeInputCounts> counts,
                                 std::span<char> output);

// Dormant diagnostic, one synchronous run per instance across both entry points.
// Keep the input buffer off small task stacks. STOP and ownership loss must latch
// through teardown. No PCM leaves the trial.
class K151MicWakeTrial final {
 public:
  static const char* compiled_link_marker();
  using ListenStarted = void (*)();
  explicit K151MicWakeTrial(ListenStarted on_listen = nullptr) : on_listen_(on_listen) {}

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

 private:
  std::optional<K151MicWakeTrialResult> begin(const std::atomic_bool& owner,
                                             const std::atomic_bool& stop,
                                             const K151MicOnlyEvidence& evidence) {
    input_counts_.reset();
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
  ListenStarted on_listen_;
  bool attempted_ = false;
};

}  // namespace stackchan::standalone

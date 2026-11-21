// SPDX-License-Identifier: MIT
#pragma once

#include "k151_mic_only_evidence.hpp"
#include "native_wake_input.hpp"
#include <atomic>
#include <memory>
#include <optional>

namespace stackchan::standalone {

enum class K151MicWakeTrialResult { denied, stopped, not_detected, detected, fault, memory_denied };

// Dormant diagnostic, one synchronous run per instance across both entry points.
// Keep the input buffer off small task stacks. STOP and ownership loss must latch
// through teardown. No PCM leaves the trial.
class K151MicWakeTrial final {
 public:
  static const char* compiled_link_marker();

  // The local owner supplies current electrical evidence and the whole linked
  // model pack. The trial verifies it before giving the mic path a model.
  K151MicWakeTrialResult run_embedded(const std::atomic_bool& owner, const std::atomic_bool& stop,
                                     const K151MicOnlyEvidence& evidence,
                                     std::span<const uint8_t> pack);

  // Adapter boundary for a preverified exclusive model or a host test double.
  // Passing ownership consumes the model even when the trial is denied.
  K151MicWakeTrialResult run(const std::atomic_bool& owner, const std::atomic_bool& stop,
                            const K151MicOnlyEvidence& evidence,
                            std::unique_ptr<NativeWakePort> model);

 private:
  std::optional<K151MicWakeTrialResult> begin(const std::atomic_bool& owner,
                                             const std::atomic_bool& stop,
                                             const K151MicOnlyEvidence& evidence) {
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
  bool attempted_ = false;
};

}  // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
#pragma once

#include "k151_codec_port.hpp"
#include "native_wake_input.hpp"
#include <memory>

namespace stackchan::standalone {

enum class K151MicWakeTrialResult { denied, stopped, not_detected, detected, fault };

// Dormant diagnostic. The exclusive local owner supplies current electrical
// evidence and a verified local model. Keep this buffer off small task stacks.
// STOP and ownership loss must latch through teardown. One synchronous run per
// instance. Model ownership is consumed even on denial. No PCM leaves the trial.
class K151MicWakeTrial final {
 public:
  K151MicWakeTrialResult run(const std::atomic_bool& owner, const std::atomic_bool& stop,
                            const K151MicOnlyEvidence& evidence,
                            std::unique_ptr<NativeWakePort> model);

 private:
  NativeWakeInput input_;
  bool attempted_ = false;
};

}  // namespace stackchan::standalone

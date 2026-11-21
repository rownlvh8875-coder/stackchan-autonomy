// SPDX-License-Identifier: MIT
#include "k151_mic_wake_trial.hpp"
#include "k151_wakenet_port.hpp"
#include <new>
#include <utility>

namespace stackchan::standalone {

K151MicWakeTrialResult K151MicWakeTrial::run_embedded(const std::atomic_bool& owner,
                                                     const std::atomic_bool& stop,
                                                     const K151MicOnlyEvidence& evidence,
                                                     std::span<const uint8_t> pack) {
  if (const auto denied = begin(owner, stop, evidence)) return *denied;

  std::unique_ptr<K151WakeNetPort> model{new (std::nothrow) K151WakeNetPort};
  if (!model || !model->prepare_embedded(owner, stop, pack)) {
    model.reset();
    return stop.load() || !owner.load() ? K151MicWakeTrialResult::stopped
                                        : K151MicWakeTrialResult::fault;
  }
  return run_prepared(owner, stop, evidence, std::move(model));
}

const char* K151MicWakeTrial::compiled_link_marker() {
  auto volatile anchor = &K151MicWakeTrial::run_embedded;
  (void)anchor;
  return "K151 embedded model and microphone diagnostic compiled; NOT STARTED";
}

}  // namespace stackchan::standalone

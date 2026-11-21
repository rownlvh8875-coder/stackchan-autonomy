// SPDX-License-Identifier: MIT
#include "k151_mic_wake_trial.hpp"
#include "k151_mic_wake_memory.hpp"
#include "k151_wakenet_port.hpp"
#include <new>
#include <utility>

namespace stackchan::standalone {

K151MicWakeTrialResult K151MicWakeTrial::run_embedded(const std::atomic_bool& owner,
                                                     const std::atomic_bool& stop,
                                                     const K151MicOnlyEvidence& evidence,
                                                     std::span<const uint8_t> pack) {
  if (const auto denied = begin(owner, stop, evidence)) return *denied;
  const auto allowed = [&] { return owner.load() && !stop.load(); };

  const bool baseline_available = k151_mic_wake_internal_heap_available();
  if (!allowed()) return K151MicWakeTrialResult::stopped;
  if (!baseline_available) return K151MicWakeTrialResult::memory_denied;
  std::unique_ptr<K151WakeNetPort> model{new (std::nothrow) K151WakeNetPort};
  if (!model || !model->prepare_embedded(owner, stop, pack)) {
    model.reset();
    return allowed() ? K151MicWakeTrialResult::fault : K151MicWakeTrialResult::stopped;
  }
  return run_prepared(owner, stop, evidence, std::move(model));
}

const char* K151MicWakeTrial::compiled_link_marker() {
  auto volatile anchor = &K151MicWakeTrial::run_embedded;
  (void)anchor;
  return "K151 embedded model and microphone diagnostic compiled; NOT STARTED";
}

}  // namespace stackchan::standalone

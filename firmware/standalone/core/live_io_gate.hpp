// SPDX-License-Identifier: MIT
// No device/network dependency. Every I/O boundary must re-check live network
// readiness, owner permission and physical STOP. Revocation is irreversible.
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <utility>

namespace stackchan::standalone {

class LiveIoGate final {
 public:
  LiveIoGate(std::function<bool()> network_ready,
             const std::atomic_bool& owner_consent,
             const std::atomic_bool& physical_stop,
             uint64_t deadline_ms)
      : network_ready_(std::move(network_ready)), owner_(owner_consent),
        stop_(physical_stop), deadline_ms_(deadline_ms) {}

  bool allowed(uint64_t monotonic_ms) {
    if (revoked_ || !network_ready_ ||
        monotonic_ms >= deadline_ms_ ||
        !owner_.load(std::memory_order_acquire) ||
        stop_.load(std::memory_order_acquire) ||
        !network_ready_()) {
      revoked_ = true;
      return false;
    }
    return true;
  }
  bool revoked() const { return revoked_; }

 private:
  std::function<bool()> network_ready_;
  const std::atomic_bool& owner_;
  const std::atomic_bool& stop_;
  uint64_t deadline_ms_;
  bool revoked_ = false; // Exactly one owning HTTP task; never shared.
};

}  // namespace stackchan::standalone

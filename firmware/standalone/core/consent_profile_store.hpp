// SPDX-License-Identifier: MIT
// Portable, fail-closed bridge from SCFG feature validation to durable storage.
// Physical owner consent MUST originate outside USB and the cloud.
#pragma once

#include "persistent_store.hpp"

#include <atomic>
#include <functional>
#include <span>
#include <utility>

namespace stackchan::standalone {

class ConsentProfileStore final {
 public:
  using SetWritePermission = std::function<void(bool)>;
  ConsentProfileStore(PersistentGuard& guard,
                      const std::atomic_bool& physical_enrollment,
                      const std::atomic_bool& physical_stop,
                      SetWritePermission permit)
      : guard_(guard), physical_enrollment_(physical_enrollment),
        physical_stop_(physical_stop), permit_(std::move(permit)) {}

  ConsentProfileStore(const ConsentProfileStore&) = delete;
  ConsentProfileStore& operator=(const ConsentProfileStore&) = delete;

  // Called ONLY after EnrollmentServer decoded and verified a SWK1 profile.
  // This rechecks both independent local latches at the exact storage boundary.
  bool persist(std::span<const uint8_t> profile) {
    if (!permit_ || guard_.fatal() ||
        !physical_enrollment_.load(std::memory_order_acquire) ||
        physical_stop_.load(std::memory_order_acquire) ||
        write_busy_.test_and_set(std::memory_order_acquire)) return false;

    // The actual NVS adapter checks this scoped gate independently. It must
    // never remain armed after an ACK, NVS error, STOP, or successful write.
    permit_(true);
    const bool saved = guard_.save_profile(
        profile, physical_enrollment_.load(std::memory_order_acquire) &&
                     !physical_stop_.load(std::memory_order_acquire));
    permit_(false);
    write_busy_.clear(std::memory_order_release);

    // STOP can race an NVS commit: this return value prevents an ACK saying
    // success but does NOT claim that already-written bytes were rolled back.
    return saved && !physical_stop_.load(std::memory_order_acquire) &&
           physical_enrollment_.load(std::memory_order_acquire);
  }

 private:
  PersistentGuard& guard_;
  const std::atomic_bool& physical_enrollment_;
  const std::atomic_bool& physical_stop_;
  SetWritePermission permit_;
  std::atomic_flag write_busy_ = ATOMIC_FLAG_INIT;
};

}  // namespace stackchan::standalone

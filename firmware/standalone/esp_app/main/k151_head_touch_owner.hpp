// SPDX-License-Identifier: MIT
// Compile-only adapter for factory Si12T head touch, address 0x68 / register 0x10.
// The HOLD app never constructs this class, adds an I2C device or reads touch.
#pragma once

#include "head_touch_consent.hpp"

#include <array>
#include <atomic>
#include <cstdint>
#include <driver/i2c_master.h>

namespace stackchan::standalone {

class K151LocalOwnerSetup;

class K151HeadTouchOwner final {
 public:
  static const char* compiled_link_marker();
  // physical_owner_mode is a dedicated local control latch. This is only
  // physical presence, NOT authenticated owner identity.
  K151HeadTouchOwner(std::atomic_bool& physical_owner_mode,
                    const std::atomic_bool& physical_stop)
      : owner_mode_(physical_owner_mode), stop_(physical_stop) {
    owner_mode_.store(false, std::memory_order_release);
  }
  K151HeadTouchOwner(const K151HeadTouchOwner&) = delete;
  K151HeadTouchOwner& operator=(const K151HeadTouchOwner&) = delete;
  ~K151HeadTouchOwner();

  // The caller supplies an already initialized I2C bus that it exclusively
  // controls; this class never starts a bus or configures touch sensitivity.
  // `sensor_preinitialized` must come from independent hardware inspection.
  bool attach_readonly(i2c_master_bus_handle_t borrowed_bus,
                       bool board_identity_verified,
                       bool sensor_preinitialized,
                       bool exclusive_bus_control,
                       uint64_t monotonic_ms);
  TouchConsentEvent poll_once(uint64_t monotonic_ms);
  // Device-local owner UI and head touch evidence are both required.
  bool begin_owner_setup(K151LocalOwnerSetup& setup, bool trusted_local_ui,
                         uint64_t monotonic_ms);
  bool request_final_confirmation(K151LocalOwnerSetup& setup,
                                  bool trusted_local_reviewed,
                                  uint64_t monotonic_ms);
  bool finish_owner_setup(K151LocalOwnerSetup& setup,
                          uint64_t monotonic_ms);
  bool owner_window_open(uint64_t monotonic_ms) const;
  void revoke();
  bool detach_readonly();
  bool faulted() const { return faulted_; }

 private:
  bool failed();
  std::atomic_bool& owner_mode_;
  const std::atomic_bool& stop_;
  HeadTouchConsent gesture_;
  i2c_master_dev_handle_t dev_ = nullptr;
  bool attempted_ = false;
  bool faulted_ = false;
};

}  // namespace stackchan::standalone

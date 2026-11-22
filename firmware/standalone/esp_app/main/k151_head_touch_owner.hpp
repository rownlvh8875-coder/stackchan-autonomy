// SPDX-License-Identifier: MIT
// K151 Si12T setup and physical-presence input. The HOLD app does not start it.
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

  // The caller owns the registered board bus. Use the read-only path only
  // with independently confirmed sensor configuration.
  bool attach_readonly(i2c_master_bus_handle_t borrowed_bus,
                       bool board_identity_verified,
                       bool sensor_preinitialized,
                       bool exclusive_bus_control,
                       uint64_t monotonic_ms);
  // On the same owning task, prepare the three head pads for local setup.
  // Requires independently verified board identity and exclusive bus control.
  bool attach_for_setup(i2c_master_bus_handle_t borrowed_bus,
                        bool board_identity_verified,
                        bool exclusive_bus_control);
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
  // Revokes consent and restores any changed fields. Keep the bus alive and
  // retry detach on the owning task if the sensor cannot be released.
  bool detach();
  bool faulted() const { return faulted_; }

 private:
  // Friend access is only the one-use encrypted pairing controller, NEVER
  // the SCPS byte framing or any on-wire operation.
  friend class K151ScpsUsbPort;
  bool start_scps_final_touch(bool trusted_local_reviewed,uint64_t now_ms);
  bool take_scps_final_touch(uint64_t now_ms);
  bool attach_device(i2c_master_bus_handle_t bus, bool board_verified,
                     bool exclusive_bus_control);
  bool read_register(uint8_t reg, uint8_t& value) const;
  bool write_register(uint8_t reg, uint8_t value) const;
  bool read_setup_mode() const;
  bool configure_pads();
  bool restore_pads();
  bool failed();
  std::atomic_bool& owner_mode_;
  const std::atomic_bool& stop_;
  HeadTouchConsent gesture_;
  struct PadField { uint8_t reg, mask, required; };
  static constexpr std::array<PadField, 5> kPadFields{{
      {0x02, 0xff, 0x33}, // Factory low range, level 3, channels 1 and 2.
      {0x03, 0x0f, 0x03}, // Same setting on channel 3. Preserve channel 4.
      {0x0a, 0x07, 0x00}, // Release forced reference reset for channels 1-3.
      {0x0e, 0x07, 0x00}, // Enable automatic calibration for channels 1-3.
      {0x0c, 0x07, 0x00}, // Enable sensing after the preceding settings.
  }};
  std::array<uint8_t, kPadFields.size()> original_{};
  std::array<bool, kPadFields.size()> changed_{};
  i2c_master_dev_handle_t dev_ = nullptr;
  bool attempted_ = false;
  bool faulted_ = false;
};

}  // namespace stackchan::standalone

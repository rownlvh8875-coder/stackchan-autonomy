// SPDX-License-Identifier: MIT
// Off-device K151 installation HOLD and STOP sequencing only.
// No GPIO, I2C, I2S, flash, NVS write, network or physical hardware access.
#pragma once

#include "persistent_store.hpp"
#include "standalone_core.hpp"

#include <atomic>
#include <cstdint>
#include <functional>
#include <utility>

namespace stackchan::standalone {

// Independently verifiable evidence, not assertions supplied by USB, GPT,
// connected PC scripts or vendor image names. No field is assumed true.
struct RecoveryReadiness {
  bool original_a_b_verified = false;
  bool separately_preserved_backup = false;
  bool validated_recovery_path = false;
  bool live_device_identity_unchanged = false;
  bool active_slot_and_boot_selection_known = false;
  bool physical_stop_measured = false;
  bool exact_lcd_variant_verified = false;
  bool exclusive_i2c_bus_verified = false;
  bool power_rails_measured = false;
  bool amp_mute_measured = false;
  bool explicit_new_install_authorization = false;
};

// Even complete evidence must not turn this compilation into an installer.
// Firmware is still the HOLD variant, without a hardware bring-up executor.
enum class InstallHoldReason : uint8_t {
  original_missing, offsite_missing, restore_unproven,
  identity_unknown, app_slot_unknown, stop_unmeasured,
  lcd_unknown, i2c_ownership_unknown, power_unknown,
  amp_mute_unknown, new_approval_missing, deliberately_disabled
};
inline InstallHoldReason assess_install_hold(const RecoveryReadiness& e) {
  if (!e.original_a_b_verified) return InstallHoldReason::original_missing;
  if (!e.separately_preserved_backup) return InstallHoldReason::offsite_missing;
  if (!e.validated_recovery_path) return InstallHoldReason::restore_unproven;
  if (!e.live_device_identity_unchanged) return InstallHoldReason::identity_unknown;
  if (!e.active_slot_and_boot_selection_known) return InstallHoldReason::app_slot_unknown;
  if (!e.physical_stop_measured) return InstallHoldReason::stop_unmeasured;
  if (!e.exact_lcd_variant_verified) return InstallHoldReason::lcd_unknown;
  if (!e.exclusive_i2c_bus_verified) return InstallHoldReason::i2c_ownership_unknown;
  if (!e.power_rails_measured) return InstallHoldReason::power_unknown;
  if (!e.amp_mute_measured) return InstallHoldReason::amp_mute_unknown;
  if (!e.explicit_new_install_authorization) return InstallHoldReason::new_approval_missing;
  return InstallHoldReason::deliberately_disabled;
}
inline constexpr bool kHardwareActivationInHoldImage = false;
inline bool can_activate_hardware(const RecoveryReadiness&) {
  // No runtime flag, local boolean, SCPS packet or cloud output bypasses HOLD.
  return kHardwareActivationInHoldImage;
}

struct PeripheralStopHooks {
  std::function<bool()> microphone_off;
  std::function<bool()> amplifier_off;
  std::function<bool()> abort_http;
  std::function<bool()> close_usb;
  std::function<bool()> remove_display;
  std::function<bool()> release_i2c;
};

// A future hardware owner task may supply bounded callbacks. STOP admission
// is *latched before* performing any potentially blocking driver call.
// This does not prove electrical torque removal or a hard deadline.
class PeripheralStopSupervisor final {
 public:
  PeripheralStopSupervisor(std::atomic_bool& latch, Session& session,
                           PersistentGuard& budget, PeripheralStopHooks hooks)
      : latch_(latch), session_(session), budget_(budget),
        hooks_(std::move(hooks)) {}
  PeripheralStopSupervisor(const PeripheralStopSupervisor&) = delete;
  PeripheralStopSupervisor& operator=(const PeripheralStopSupervisor&) = delete;

  bool request_stop() {
    if (handled_) return !faulted_;
    handled_ = true;  // One way. No automatic retry or reactivation.
    latch_.store(true, std::memory_order_release);
    session_.stop();
    budget_.cancel_permit();

    // Deliberately invoke ALL stop callbacks independently even when an
    // earlier one fails. Leave software admission disabled on uncertainty.
    const bool microphone = quiet(hooks_.microphone_off);
    const bool amplifier = quiet(hooks_.amplifier_off);
    const bool network = quiet(hooks_.abort_http);
    const bool usb = quiet(hooks_.close_usb);
    const bool display = quiet(hooks_.remove_display);
    const bool i2c = quiet(hooks_.release_i2c);
    faulted_ = !(microphone && amplifier && network &&
                 usb && display && i2c);
    return !faulted_;
  }
  bool stopped() const { return handled_; }
  bool faulted() const { return faulted_; }

 private:
  static bool quiet(const std::function<bool()>& callback) {
    return callback && callback();
  }
  std::atomic_bool& latch_;
  Session& session_;
  PersistentGuard& budget_;
  PeripheralStopHooks hooks_;
  bool handled_ = false;
  bool faulted_ = false;
};

}  // namespace stackchan::standalone

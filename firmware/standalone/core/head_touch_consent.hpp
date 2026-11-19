// SPDX-License-Identifier: MIT
// Physical-presence gesture policy for K151 Si12T 3-pad head touch.
// No GPIO, I2C, ESP-IDF, network, flash, or secret processing.
#pragma once

#include <array>
#include <cstdint>
#include <limits>

namespace stackchan::standalone {

enum class TouchConsentPhase : uint8_t {
  hold, clear_for_arm, wait_arm_press, arm_press, arm_release,
  owner_window, clear_for_confirm, wait_confirm_press,
  confirm_press, confirm_release, confirmed, consumed, stopped, fault
};
enum class TouchConsentEvent : uint8_t {
  none, owner_window_open, final_confirmed, invalidated
};

class HeadTouchConsent final {
 public:
  // Samples must arrive within kMaxSampleGapMs while this policy is active.
  // Expected 50-ms polling comes from the pinned M5Stack Si12T driver.
  static constexpr uint64_t kMaxSampleGapMs = 250;
  static constexpr uint64_t kReleaseMs = 300;
  static constexpr uint64_t kArmHoldMs = 3000;
  static constexpr uint64_t kConfirmHoldMs = 3000;
  static constexpr uint64_t kFirstGestureTimeoutMs = 30000;
  static constexpr uint64_t kOwnerWindowMs = 120000;
  static constexpr uint64_t kConfirmTicketMs = 15000;

  bool begin(bool sensor_driver_exclusively_owned, uint64_t now_ms) {
    if (phase_ != TouchConsentPhase::hold || !sensor_driver_exclusively_owned ||
        now_ms > std::numeric_limits<uint64_t>::max() -
                      (kOwnerWindowMs + kFirstGestureTimeoutMs)) return false;
    phase_ = TouchConsentPhase::clear_for_arm;
    began_ms_ = now_ms;
    last_ms_ = now_ms;
    release_active_ = false;
    return true;
  }

  TouchConsentPhase phase() const { return phase_; }
  bool owner_window_open(uint64_t now_ms) const {
    return (phase_ == TouchConsentPhase::owner_window ||
            phase_ == TouchConsentPhase::clear_for_confirm ||
            phase_ == TouchConsentPhase::wait_confirm_press ||
            phase_ == TouchConsentPhase::confirm_press ||
            phase_ == TouchConsentPhase::confirm_release ||
            phase_ == TouchConsentPhase::confirmed) &&
           now_ms >= last_ms_ && now_ms - last_ms_ <= kMaxSampleGapMs &&
           now_ms <= owner_deadline_ms_;
  }

  TouchConsentEvent sample(const std::array<uint8_t, 3>& pad_intensity,
                           uint64_t now_ms, bool read_succeeded,
                           bool physical_stop) {
    if (physical_stop) return stop();
    if (phase_ == TouchConsentPhase::stopped ||
        phase_ == TouchConsentPhase::fault ||
        phase_ == TouchConsentPhase::hold ||
        phase_ == TouchConsentPhase::consumed) return TouchConsentEvent::none;
    if (!read_succeeded || now_ms < last_ms_ ||
        now_ms - last_ms_ > kMaxSampleGapMs) return fault();
    for (uint8_t value : pad_intensity) if (value > 3) return fault();
    last_ms_ = now_ms;
    if (began_ms_ > now_ms ||
        (phase_ < TouchConsentPhase::owner_window &&
         now_ms - began_ms_ >= kFirstGestureTimeoutMs)) return fault();
    if (phase_ >= TouchConsentPhase::owner_window &&
        now_ms > owner_deadline_ms_) return fault();
    if (phase_ == TouchConsentPhase::confirmed &&
        now_ms > confirm_deadline_ms_) return fault();
    const bool touched = pad_intensity[0] != 0 ||
                         pad_intensity[1] != 0 || pad_intensity[2] != 0;
    switch (phase_) {
      case TouchConsentPhase::clear_for_arm:
        if (stable_release(touched, now_ms)) phase_ = TouchConsentPhase::wait_arm_press;
        break;
      case TouchConsentPhase::wait_arm_press:
        if (touched) { press_start_ms_ = now_ms;
                       phase_ = TouchConsentPhase::arm_press; }
        break;
      case TouchConsentPhase::arm_press:
        if (!touched) { enter_release(TouchConsentPhase::clear_for_arm); }
        else if (now_ms - press_start_ms_ >= kArmHoldMs) {
          phase_ = TouchConsentPhase::arm_release; release_active_ = false;
        }
        break;
      case TouchConsentPhase::arm_release:
        if (stable_release(touched, now_ms)) {
          phase_ = TouchConsentPhase::owner_window;
          owner_deadline_ms_ = now_ms + kOwnerWindowMs;
          return TouchConsentEvent::owner_window_open;
        }
        break;
      case TouchConsentPhase::owner_window:
        break;
      case TouchConsentPhase::clear_for_confirm:
        if (stable_release(touched, now_ms)) phase_ = TouchConsentPhase::wait_confirm_press;
        break;
      case TouchConsentPhase::wait_confirm_press:
        if (touched) { press_start_ms_ = now_ms;
                       phase_ = TouchConsentPhase::confirm_press; }
        break;
      case TouchConsentPhase::confirm_press:
        if (!touched) { enter_release(TouchConsentPhase::clear_for_confirm); }
        else if (now_ms - press_start_ms_ >= kConfirmHoldMs) {
          phase_ = TouchConsentPhase::confirm_release; release_active_ = false;
        }
        break;
      case TouchConsentPhase::confirm_release:
        if (stable_release(touched, now_ms)) {
          phase_ = TouchConsentPhase::confirmed;
          confirm_deadline_ms_ = now_ms + kConfirmTicketMs;
          return TouchConsentEvent::final_confirmed;
        }
        break;
      default: break;
    }
    return TouchConsentEvent::none;
  }

  // Must originate from an independently verified, local reviewed-config UI.
  // Never trigger this directly from USB frames or an AI/cloud message.
  bool request_final_confirmation(bool trusted_local_reviewed, uint64_t now_ms) {
    if (!trusted_local_reviewed || phase_ != TouchConsentPhase::owner_window ||
        now_ms < last_ms_ || now_ms - last_ms_ > kMaxSampleGapMs ||
        now_ms > owner_deadline_ms_) return false;
    phase_ = TouchConsentPhase::clear_for_confirm;
    release_active_ = false;
    return true;
  }

  // A one-use, short-lived indicator of HUMAN PHYSICAL PRESENCE. This is not
  // biometric identity or proof that a USB host/credential is trustworthy.
  bool take_final_confirmation(uint64_t now_ms, bool physical_stop) {
    if (physical_stop) { (void)stop(); return false; }
    if (phase_ != TouchConsentPhase::confirmed || now_ms < last_ms_ ||
        now_ms - last_ms_ > kMaxSampleGapMs ||
        now_ms > confirm_deadline_ms_ || now_ms > owner_deadline_ms_) return false;
    phase_ = TouchConsentPhase::consumed;
    return true;
  }
  TouchConsentEvent stop() {
    if (phase_ == TouchConsentPhase::stopped) return TouchConsentEvent::none;
    phase_ = TouchConsentPhase::stopped;
    clear_timers();
    return TouchConsentEvent::invalidated;
  }

 private:
  bool stable_release(bool touched, uint64_t now_ms) {
    if (touched) { release_active_ = false; return false; }
    if (!release_active_) { release_active_ = true; release_start_ms_ = now_ms; }
    return now_ms - release_start_ms_ >= kReleaseMs;
  }
  void enter_release(TouchConsentPhase destination) {
    phase_ = destination;
    release_active_ = false;
  }
  TouchConsentEvent fault() {
    phase_ = TouchConsentPhase::fault;
    clear_timers();
    return TouchConsentEvent::invalidated;
  }
  void clear_timers() {
    release_active_ = false;
    owner_deadline_ms_ = 0; confirm_deadline_ms_ = 0;
  }
  TouchConsentPhase phase_ = TouchConsentPhase::hold;
  uint64_t last_ms_ = 0;
  uint64_t began_ms_ = 0;
  uint64_t press_start_ms_ = 0;
  uint64_t release_start_ms_ = 0;
  uint64_t owner_deadline_ms_ = 0;
  uint64_t confirm_deadline_ms_ = 0;
  bool release_active_ = false;
};
}  // namespace stackchan::standalone

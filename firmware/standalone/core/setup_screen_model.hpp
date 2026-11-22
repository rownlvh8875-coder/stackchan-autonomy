// SPDX-License-Identifier: MIT
// Credential-free setup screen view model. No raw strings, keys, USB or I/O.
#pragma once

#include "head_touch_consent.hpp"
#include "owner_setup.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace stackchan::standalone {

enum class SetupScreenKind : uint8_t {
  locked, hold_to_enter, trusted_entry_required, enter_wifi, enter_api_key,
  review_on_pc, hold_to_confirm, ready, stopped, fault
};

struct SetupScreenFrame {
  SetupScreenKind kind;
  const char* title;
  const char* line1;
  const char* line2;
  // Only fixed, build-time ASCII strings ever leave the view model.
  // Never accept a user-supplied label, SSID or token as an argument.
};

inline constexpr SetupScreenFrame setup_screen_frame(
    TouchConsentPhase touch, OwnerSetupPhase setup,
    bool trusted_input_ready, bool physical_stop, bool read_failure) {
  if (physical_stop || touch == TouchConsentPhase::stopped ||
      setup == OwnerSetupPhase::stopped)
    return {SetupScreenKind::stopped, "STOPPED", "Setup disabled", "Power cycle to retry"};
  if (read_failure || touch == TouchConsentPhase::fault ||
      setup == OwnerSetupPhase::fault)
    return {SetupScreenKind::fault, "SETUP ERROR", "Do not continue", "Check device safely"};
  if (setup == OwnerSetupPhase::ready && touch == TouchConsentPhase::consumed)
    return {SetupScreenKind::ready, "SETUP READY", "RAM credentials set", "Cloud still OFF"};
  if (setup == OwnerSetupPhase::ready)
    return {SetupScreenKind::fault, "SETUP ERROR", "Missing final touch", "Cloud stays OFF"};
  if (setup == OwnerSetupPhase::confirm) {
    if (!trusted_input_ready)
      return {SetupScreenKind::fault, "SETUP ERROR", "Trusted input lost", "Cloud stays OFF"};
    if (touch == TouchConsentPhase::owner_window)
      return {SetupScreenKind::review_on_pc, "REVIEW ON PC", "Check entries privately", "Then request final touch"};
    if (touch == TouchConsentPhase::clear_for_confirm ||
        touch == TouchConsentPhase::wait_confirm_press ||
        touch == TouchConsentPhase::confirm_press ||
        touch == TouchConsentPhase::confirm_release ||
        touch == TouchConsentPhase::confirmed)
      return {SetupScreenKind::hold_to_confirm, "FINAL APPROVAL", "Hold head for 3 sec", "Release to approve"};
    return {SetupScreenKind::fault, "SETUP ERROR", "Touch state mismatch", "Cloud stays OFF"};
  }
  if (setup == OwnerSetupPhase::wifi_input || setup == OwnerSetupPhase::api_input) {
    if (!trusted_input_ready)
      return {SetupScreenKind::trusted_entry_required, "TRUSTED INPUT", "Secure PC UI needed", "No USB secrets yet"};
    if (setup == OwnerSetupPhase::wifi_input)
      return {SetupScreenKind::enter_wifi, "SET UP WI-FI", "Enter via trusted PC", "Nothing shown here"};
    return {SetupScreenKind::enter_api_key, "SET UP API", "Enter via trusted PC", "No key displayed"};
  }
  if (setup != OwnerSetupPhase::hold)
    return {SetupScreenKind::fault, "SETUP ERROR", "Invalid setup state", "Cloud stays OFF"};
  if (touch == TouchConsentPhase::owner_window && trusted_input_ready)
    return {SetupScreenKind::trusted_entry_required, "USB SETUP", "Open secure setup on PC", "Cloud stays OFF"};
  if (touch == TouchConsentPhase::owner_window ||
      touch == TouchConsentPhase::clear_for_confirm ||
      touch == TouchConsentPhase::wait_confirm_press ||
      touch == TouchConsentPhase::confirm_press ||
      touch == TouchConsentPhase::confirm_release ||
      touch == TouchConsentPhase::confirmed)
    return {SetupScreenKind::trusted_entry_required, "TRUSTED INPUT", "Secure PC UI needed", "No input path active"};
  if (touch == TouchConsentPhase::hold)
    return {SetupScreenKind::locked, "SETUP LOCKED", "No credentials loaded", "Cloud disabled"};
  return {SetupScreenKind::hold_to_enter, "SETUP PRESENCE", "Hold head for 3 sec", "Release when prompted"};
}

}  // namespace stackchan::standalone

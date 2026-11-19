// SPDX-License-Identifier: MIT
// Dormant ESP-IDF compile-only local owner setup helper: no active device input.
#pragma once

#include "owner_setup.hpp"
#include "k151_wifi_time.hpp"

#include <atomic>
#include <cstdint>
#include <span>
#include <string_view>

namespace stackchan::standalone {

// This binds the host-tested state machine but supplies NO GPIO, USB command,
// keyboard, display, or automatic trusted-input mode. The real physical
// authorization mechanism is deliberately NOT provided or guessed here.
class K151HeadTouchOwner;

class K151LocalOwnerSetup final {
 public:
  static const char* compiled_link_marker();
  K151LocalOwnerSetup(const std::atomic_bool& hardware_owner_mode,
                      const std::atomic_bool& trusted_local_input,
                      const std::atomic_bool& stop)
      : setup_(secrets_, hardware_owner_mode, trusted_local_input, stop),
        owner_(hardware_owner_mode), input_(trusted_local_input), stop_(stop) {}
  K151LocalOwnerSetup(const K151LocalOwnerSetup&) = delete;
  K151LocalOwnerSetup& operator=(const K151LocalOwnerSetup&) = delete;
  bool arm(uint64_t now_ms) { return setup_.arm(now_ms); }
  bool submit_wifi(std::span<const uint8_t> ssid, std::string_view pass,
                   uint64_t now_ms) {
    return setup_.submit_wifi(ssid, pass, now_ms);
  }
  bool submit_api_key(std::string_view key, uint64_t now_ms) {
    return setup_.submit_api_key(key, now_ms);
  }
  bool poll(uint64_t now_ms) { return setup_.tick(now_ms); }
  void stop() { setup_.cancel(); }
  bool ready() const { return setup_.ready(); }
  OwnerSetupPhase phase() const { return setup_.phase(); }
  // This can activate Wi-Fi, so it is intentionally never called from
  // app_main. Only an independently authenticated local UI may invoke it.
  // Credentials are cleared from this object immediately after handoff;
  // the Wi-Fi adapter copies them to RAM-only driver storage.
  bool start_wifi_once(K151WifiTimePort& network);

 private:
  friend class K151HeadTouchOwner;
  friend class K151ScpsUsbPort;
  // Only the sensor-owned second 3-second touch ticket may consume this
  // path. Other application code cannot impersonate final confirmation.
  bool confirm(uint64_t now_ms, bool physical_confirmation) {
    return setup_.confirm(now_ms, physical_confirmation);
  }
  RuntimeSecrets secrets_;
  OwnerSetupController setup_;
  const std::atomic_bool& owner_;
  const std::atomic_bool& input_;
  const std::atomic_bool& stop_;
  bool network_handoff_attempted_ = false;
};

}  // namespace stackchan::standalone

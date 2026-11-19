// SPDX-License-Identifier: MIT
// Dormant ESP-IDF compile-only local owner setup helper: no active device input.
#pragma once

#include "owner_setup.hpp"

#include <atomic>
#include <cstdint>
#include <span>
#include <string_view>

namespace stackchan::standalone {

// This binds the host-tested state machine but supplies NO GPIO, USB command,
// keyboard, display, or automatic trusted-input mode. The real physical
// authorization mechanism is deliberately NOT provided or guessed here.
class K151LocalOwnerSetup final {
 public:
  static const char* compiled_link_marker();
  K151LocalOwnerSetup(const std::atomic_bool& hardware_owner_mode,
                      const std::atomic_bool& trusted_local_input,
                      const std::atomic_bool& stop)
      : setup_(secrets_, hardware_owner_mode, trusted_local_input, stop) {}
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
  bool confirm(uint64_t now_ms, bool physical_confirmation) {
    return setup_.confirm(now_ms, physical_confirmation);
  }
  bool poll(uint64_t now_ms) { return setup_.tick(now_ms); }
  void stop() { setup_.cancel(); }
  bool ready() const { return setup_.ready(); }
  // Future owner-controlled runtime must read this only after ready().
  // Returned views are invalidated by cancel(), STOP and destruction.
  const RuntimeSecrets& volatile_secrets() const { return secrets_; }

 private:
  RuntimeSecrets secrets_;
  OwnerSetupController setup_;
};

}  // namespace stackchan::standalone

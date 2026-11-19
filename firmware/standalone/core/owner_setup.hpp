// SPDX-License-Identifier: MIT
// One-shot, local-only first setup. No UART, USB, GPIO, flash or network I/O.
// The three physical/security latches MUST come from a verified device-local
// owner controller, never from SCFG, HTTP, GPT output, or a generic USB frame.
#pragma once

#include "network_time_guard.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>
#include <string_view>

namespace stackchan::standalone {

enum class OwnerSetupPhase : uint8_t {
  hold, wifi_input, api_input, confirm, ready, stopped, fault
};

class OwnerSetupController final {
 public:
  static constexpr uint64_t kInputTimeoutMs = 120000;

  OwnerSetupController(RuntimeSecrets& output,
                       const std::atomic_bool& local_owner_mode,
                       const std::atomic_bool& trusted_input_surface,
                       const std::atomic_bool& physical_stop)
      : output_(output), owner_(local_owner_mode),
        input_(trusted_input_surface), stop_(physical_stop) {}
  OwnerSetupController(const OwnerSetupController&) = delete;
  OwnerSetupController& operator=(const OwnerSetupController&) = delete;
  ~OwnerSetupController() { scrub(); }

  OwnerSetupPhase phase() const { return phase_; }
  bool ready() const {
    return phase_ == OwnerSetupPhase::ready && owner_.load() &&
           input_.load() && !stop_.load() && output_.valid();
  }

  // This function MUST only be called by a trusted physical owner controller.
  // Merely connecting USB or knowing an SCFG nonce is not consent.
  bool arm(uint64_t monotonic_ms) {
    if (phase_ != OwnerSetupPhase::hold || output_.valid() ||
        !owner_.load() || !input_.load() || stop_.load() ||
        monotonic_ms > std::numeric_limits<uint64_t>::max() - kInputTimeoutMs)
      return false;
    started_ms_ = monotonic_ms;
    last_ms_ = monotonic_ms;
    phase_ = OwnerSetupPhase::wifi_input;
    return true;
  }

  bool submit_wifi(std::span<const uint8_t> ssid,
                   std::string_view passphrase, uint64_t monotonic_ms) {
    if (!step(OwnerSetupPhase::wifi_input, monotonic_ms)) return false;
    if (!valid_ssid(ssid) || !valid_password(passphrase)) return fault();
    std::copy(ssid.begin(), ssid.end(), ssid_.begin());
    std::copy(passphrase.begin(), passphrase.end(), pass_.begin());
    ssid_size_ = ssid.size();
    pass_size_ = passphrase.size();
    phase_ = OwnerSetupPhase::api_input;
    return true;
  }

  bool submit_api_key(std::string_view api_key, uint64_t monotonic_ms) {
    if (!step(OwnerSetupPhase::api_input, monotonic_ms)) return false;
    if (!valid_api_key(api_key)) return fault();
    std::copy(api_key.begin(), api_key.end(), key_.begin());
    key_size_ = api_key.size();
    phase_ = OwnerSetupPhase::confirm;
    return true;
  }

  // Separate physical confirmation after both inputs, before any consumer
  // can read the credentials. No automatic Wi-Fi/cloud call is made.
  bool confirm(uint64_t monotonic_ms, bool separately_confirmed_locally) {
    if (!step(OwnerSetupPhase::confirm, monotonic_ms)) return false;
    if (!separately_confirmed_locally || ssid_size_ == 0 ||
        pass_size_ == 0 || key_size_ == 0) return fault();

    // Copies into bounded RuntimeSecrets only; never NVS/ESP Wi-Fi storage.
    const bool provisioned = output_.provision(
        std::span<const uint8_t>(ssid_.data(), ssid_size_),
        std::string_view(pass_.data(), pass_size_),
        std::string_view(key_.data(), key_size_), true);
    scrub();
    if (!provisioned || !owner_.load() || !input_.load() || stop_.load()) {
      return fault();
    }
    phase_ = OwnerSetupPhase::ready;
    return true;
  }

  // Must be polled by a trusted local controller. Power loss wipes RAM.
  bool tick(uint64_t monotonic_ms) {
    if (phase_ == OwnerSetupPhase::stopped ||
        phase_ == OwnerSetupPhase::fault) return false;
    if (phase_ == OwnerSetupPhase::hold) return false;
    if (stop_.load() || !owner_.load() || !input_.load()) {
      cancel();
      return false;
    }
    if (monotonic_ms < last_ms_) return fault();
    last_ms_ = monotonic_ms;
    if (phase_ != OwnerSetupPhase::ready &&
        monotonic_ms - started_ms_ >= kInputTimeoutMs) return fault();
    return true;
  }

  void cancel() {
    scrub();
    if (phase_ != OwnerSetupPhase::hold) output_.clear();
    phase_ = OwnerSetupPhase::stopped;
  }

 private:
  bool step(OwnerSetupPhase required, uint64_t now) {
    if (phase_ != required) {
      if (phase_ != OwnerSetupPhase::hold &&
          phase_ != OwnerSetupPhase::stopped &&
          phase_ != OwnerSetupPhase::fault &&
          phase_ != OwnerSetupPhase::ready) (void)fault();
      return false;
    }
    return tick(now);
  }
  bool fault() {
    scrub();
    output_.clear();
    phase_ = OwnerSetupPhase::fault;
    return false;
  }
  void scrub() noexcept {
    wipe_secret(reinterpret_cast<volatile unsigned char*>(ssid_.data()),
                ssid_.size());
    wipe_secret(reinterpret_cast<volatile unsigned char*>(pass_.data()),
                pass_.size());
    wipe_secret(reinterpret_cast<volatile unsigned char*>(key_.data()),
                key_.size());
    ssid_size_ = 0; pass_size_ = 0; key_size_ = 0;
  }
  static bool valid_ssid(std::span<const uint8_t> ssid) {
    if (ssid.empty() || ssid.size() > 32) return false;
    for (const auto ch: ssid) if (ch < 0x20 || ch == 0x7f) return false;
    return true;
  }
  static bool valid_password(std::string_view pass) {
    if (pass.size() < 8 || pass.size() > 64) return false;
    bool all_hex = true;
    for (const auto c: pass) {
      const auto b = static_cast<unsigned char>(c);
      if (b < 0x20 || b > 0x7e) return false;
      if (!((b >= '0' && b <= '9') || (b >= 'a' && b <= 'f') ||
            (b >= 'A' && b <= 'F'))) all_hex = false;
    }
    return pass.size() != 64 || all_hex;
  }
  static bool valid_api_key(std::string_view key) {
    if (key.size() < 16 || key.size() > 220) return false;
    for (const auto c: key) {
      const auto b = static_cast<unsigned char>(c);
      if (b <= 0x20 || b >= 0x7f) return false;
    }
    return true;
  }

  RuntimeSecrets& output_;
  const std::atomic_bool& owner_;
  const std::atomic_bool& input_;
  const std::atomic_bool& stop_;
  std::array<uint8_t,32> ssid_{};
  std::array<char,64> pass_{};
  std::array<char,224> key_{};
  size_t ssid_size_ = 0;
  size_t pass_size_ = 0;
  size_t key_size_ = 0;
  uint64_t started_ms_ = 0;
  uint64_t last_ms_ = 0;
  OwnerSetupPhase phase_ = OwnerSetupPhase::hold;
};

}  // namespace stackchan::standalone

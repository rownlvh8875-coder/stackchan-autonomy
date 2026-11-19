// SPDX-License-Identifier: MIT
// K151 standalone: host-testable Wi-Fi/IP/time policy, with NO device I/O.
#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <string_view>

namespace stackchan::standalone {

// Scope-limited, RAM-only secrets. Nothing in this class persists to NVS,
// formats device settings, emits logs, or opens a network connection.
inline void wipe_secret(volatile unsigned char* ptr, size_t n) noexcept {
  for (size_t i = 0; i < n; ++i) ptr[i] = 0;
}

class RuntimeSecrets final {
 public:
  RuntimeSecrets() = default;
  RuntimeSecrets(const RuntimeSecrets&) = delete;
  RuntimeSecrets& operator=(const RuntimeSecrets&) = delete;
  ~RuntimeSecrets() { clear(); }

  bool provision(std::span<const uint8_t> ssid, std::string_view passphrase,
                 std::string_view api_key, bool explicit_local_owner) {
    clear();
    if (!explicit_local_owner || !valid_wifi(ssid, passphrase) ||
        !valid_api_key(api_key)) return false;
    std::copy(ssid.begin(), ssid.end(), ssid_.begin());
    std::copy(passphrase.begin(), passphrase.end(), passphrase_.begin());
    std::copy(api_key.begin(), api_key.end(), api_key_.begin());
    ssid_size_ = ssid.size();
    pass_size_ = passphrase.size();
    key_size_ = api_key.size();
    valid_ = true;
    return true;
  }
  bool valid() const { return valid_; }
  // Only a device-local, separately owner-authorized network port may read
  // these views, which become invalid after clear()/destruction.
  std::span<const uint8_t> ssid() const { return {ssid_.data(), ssid_size_}; }
  std::string_view passphrase() const { return {passphrase_.data(), pass_size_}; }
  std::string_view api_key() const { return {api_key_.data(), key_size_}; }
  void clear() noexcept {
    wipe_secret(reinterpret_cast<volatile unsigned char*>(ssid_.data()), ssid_.size());
    wipe_secret(reinterpret_cast<volatile unsigned char*>(passphrase_.data()), passphrase_.size());
    wipe_secret(reinterpret_cast<volatile unsigned char*>(api_key_.data()), api_key_.size());
    ssid_size_ = 0;
    pass_size_ = 0;
    key_size_ = 0;
    valid_ = false;
  }
 private:
  static bool valid_wifi(std::span<const uint8_t> ssid, std::string_view pass) {
    if (ssid.empty() || ssid.size() > 32 || pass.size() < 8 || pass.size() > 64)
      return false;
    for (uint8_t c : ssid) if (c < 0x20 || c == 0x7f) return false;
    bool hex = pass.size() == 64;
    for (unsigned char c : pass) {
      if (c < 0x20 || c > 0x7e) return false;
      if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
            (c >= 'A' && c <= 'F'))) hex = false;
    }
    return pass.size() != 64 || hex;
  }
  static bool valid_api_key(std::string_view key) {
    if (key.size() < 16 || key.size() > 220) return false;
    for (unsigned char c : key) if (c <= 0x20 || c > 0x7e) return false;
    return true;
  }
  std::array<uint8_t, 32> ssid_{};
  std::array<char, 64> passphrase_{};
  std::array<char, 224> api_key_{};
  size_t ssid_size_ = 0, pass_size_ = 0, key_size_ = 0;
  bool valid_ = false;
};

enum class ConnectivityPhase : uint8_t {
  hold, offline, associating, associated, waiting_time, ready, stopped, fault
};

class NetworkTimeGuard final {
 public:
  static constexpr uint64_t kMaxClockAgeMs = 15ULL * 60ULL * 1000ULL;
  static constexpr uint64_t kMaxWallSkewSeconds = 10;
  static constexpr uint64_t kMinPlausibleEpoch = 1700000000ULL;
  static constexpr uint64_t kMaxPlausibleEpoch = 4102444800ULL;
  static constexpr uint64_t kMaxRetryMs = 60000;

  bool arm(bool explicit_local_owner, bool have_ram_credentials,
           uint64_t monotonic_ms) {
    if (phase_ != ConnectivityPhase::hold || !explicit_local_owner ||
        !have_ram_credentials) return false;
    phase_ = ConnectivityPhase::offline;
    last_ms_ = monotonic_ms;
    due_ms_ = monotonic_ms;
    return true;
  }
  ConnectivityPhase phase() const { return phase_; }
  uint64_t attempt_id() const { return attempt_; }
  uint64_t next_retry_ms() const { return due_ms_; }
  unsigned failures() const { return failures_; }
  bool stopped() const { return phase_ == ConnectivityPhase::stopped; }

  // Called from one owning task, never concurrently from an ESP event callback.
  // Drivers must queue events and filter stale association epochs themselves.
  bool tick(uint64_t monotonic_ms) {
    if (monotonic_ms < last_ms_) { fault(); return false; }
    last_ms_ = monotonic_ms;
    if (phase_ == ConnectivityPhase::ready &&
        monotonic_ms - sync_ms_ > kMaxClockAgeMs) {
      phase_ = ConnectivityPhase::waiting_time;
    }
    return phase_ != ConnectivityPhase::stopped &&
           phase_ != ConnectivityPhase::fault;
  }
  std::optional<uint64_t> claim_connect(uint64_t now_ms) {
    if (!tick(now_ms) || phase_ != ConnectivityPhase::offline ||
        now_ms < due_ms_) return std::nullopt;
    if (attempt_ == std::numeric_limits<uint64_t>::max()) {
      fault(); return std::nullopt;
    }
    ++attempt_;
    phase_ = ConnectivityPhase::associating;
    return attempt_;
  }
  bool associated(uint64_t id, uint64_t now_ms) {
    if (!tick(now_ms) || phase_ != ConnectivityPhase::associating ||
        id != attempt_) return false;
    phase_ = ConnectivityPhase::associated;
    return true;
  }
  bool ip_acquired(uint64_t id, uint64_t now_ms) {
    if (!tick(now_ms) || phase_ != ConnectivityPhase::associated ||
        id != attempt_) return false;
    phase_ = ConnectivityPhase::waiting_time;
    return true;
  }
  void disconnected(uint64_t now_ms) {
    if (!tick(now_ms) || phase_ == ConnectivityPhase::hold ||
        phase_ == ConnectivityPhase::offline) return;
    phase_ = ConnectivityPhase::offline;
    if (failures_ < 255) ++failures_;
    const unsigned shift = std::min<unsigned>(failures_ - 1U, 6U);
    const uint64_t delay = std::min<uint64_t>(kMaxRetryMs, uint64_t{1000} << shift);
    due_ms_ = now_ms > UINT64_MAX - delay ? UINT64_MAX : now_ms + delay;
  }
  bool time_synchronized(uint64_t id, uint64_t epoch_seconds,
                         uint64_t monotonic_ms) {
    if (!tick(monotonic_ms) || phase_ != ConnectivityPhase::waiting_time ||
        id != attempt_ || epoch_seconds < kMinPlausibleEpoch ||
        epoch_seconds > kMaxPlausibleEpoch) return false;
    // A large calendar-time jump within one uninterrupted boot is unsafe for
    // rolling budget accounting. SNTP is unauthenticated; this is *plausibility*
    // protection, NOT cryptographic proof of correct UTC.
    if (have_anchor_) {
      if (monotonic_ms < sync_ms_) { fault(); return false; }
      const uint64_t estimate = sync_epoch_ + (monotonic_ms - sync_ms_) / 1000U;
      const uint64_t skew = estimate >= epoch_seconds ? estimate - epoch_seconds :
                            epoch_seconds - estimate;
      if (skew > kMaxWallSkewSeconds) { fault(); return false; }
    }
    sync_epoch_ = epoch_seconds;
    sync_ms_ = monotonic_ms;
    have_anchor_ = true;
    failures_ = 0;
    phase_ = ConnectivityPhase::ready;
    return true;
  }
  bool can_attempt_paid_request(uint64_t monotonic_ms,
                                uint64_t system_epoch_seconds,
                                bool owner_paid_consent,
                                bool physical_stop) const {
    if (phase_ != ConnectivityPhase::ready || !have_anchor_ ||
        physical_stop || !owner_paid_consent ||
        monotonic_ms < sync_ms_ || monotonic_ms < last_ms_ ||
        monotonic_ms - sync_ms_ > kMaxClockAgeMs) return false;
    const uint64_t estimated = sync_epoch_ + (monotonic_ms - sync_ms_) / 1000U;
    const uint64_t skew = estimated >= system_epoch_seconds ?
        estimated - system_epoch_seconds : system_epoch_seconds - estimated;
    return skew <= kMaxWallSkewSeconds;
  }
  void stop() { phase_ = ConnectivityPhase::stopped; }
  void fault() { phase_ = ConnectivityPhase::fault; }
 private:
  ConnectivityPhase phase_ = ConnectivityPhase::hold;
  uint64_t last_ms_ = 0;
  uint64_t due_ms_ = 0;
  uint64_t attempt_ = 0;
  uint64_t sync_epoch_ = 0;
  uint64_t sync_ms_ = 0;
  unsigned failures_ = 0;
  bool have_anchor_ = false;
};

}  // namespace stackchan::standalone

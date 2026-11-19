// SPDX-License-Identifier: MIT
// Dormant K151 SCPS P-256/HKDF/AES-256-GCM pairing prototype.
// NOT activated from HOLD app_main; NOT a production provisioning service.
#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <span>
#include <psa/crypto.h>

namespace stackchan::standalone {

class PairingCredentials final {
 public:
  PairingCredentials() = default;
  PairingCredentials(const PairingCredentials&) = delete;
  PairingCredentials& operator=(const PairingCredentials&) = delete;
  ~PairingCredentials() { clear(); }
  void clear() noexcept;
  std::span<const uint8_t> ssid() const { return {ssid_.data(), ssid_len_}; }
  std::span<const char> password() const { return {password_.data(), password_len_}; }
  std::span<const char> api_key() const { return {key_.data(), key_len_}; }
  bool valid() const { return ssid_len_ != 0 && password_len_ != 0 && key_len_ != 0; }
 private:
  friend class K151SecurePcSetup;
  std::array<uint8_t,32> ssid_{};
  std::array<char,64> password_{};
  std::array<char,224> key_{};
  size_t ssid_len_=0, password_len_=0, key_len_=0;
};

class K151SecurePcSetup final {
 public:
  static constexpr size_t kHelloBytes=86;
  static constexpr size_t kSealedHeaderBytes=19;
  static constexpr size_t kMaxPayload=324;
  static constexpr size_t kMaxSealedBytes=kSealedHeaderBytes+kMaxPayload+16;
  static constexpr uint64_t kSessionMs=120000;

  static const char* compiled_link_marker();
  explicit K151SecurePcSetup(const std::atomic_bool& physical_stop) : stop_(physical_stop) {}
  K151SecurePcSetup(const K151SecurePcSetup&) = delete;
  K151SecurePcSetup& operator=(const K151SecurePcSetup&) = delete;
  ~K151SecurePcSetup() { stop(); }

  // A future owner-controlled task must provide VERIFIED device-local
  // physical-presence and display ownership. Neither may be a USB opcode.
  bool device_hello(uint64_t monotonic_ms, bool owner_window,
                    bool trusted_local_display,
                    std::array<uint8_t,kHelloBytes>& out);
  // SAS may be shown on a trusted LCD, NEVER sent over USB.
  bool accept_pc_hello(uint64_t monotonic_ms, bool owner_window,
                       std::span<const uint8_t> pc_hello,
                       std::array<char,9>& sas_for_local_screen);
  // This should only be called after the human verified the matching
  // 8-digit SAS on the PC and LCD. It is NOT an identity credential.
  bool open_sealed(uint64_t monotonic_ms, bool owner_window,
                   bool sas_approved_on_local_screen,
                   std::span<const uint8_t> sealed,
                   PairingCredentials& out);
  void stop();
  bool faulted() const { return fault_; }

 private:
  bool valid_time(uint64_t now) const;
  bool derive(std::span<const uint8_t> shared,
              const char* domain, uint8_t* output,size_t count);
  bool fail();
  const std::atomic_bool& stop_;
  std::array<uint8_t,kHelloBytes> device_hello_{};
  std::array<uint8_t,kHelloBytes> pc_hello_{};
  std::array<uint8_t,32> aes_key_{};
  psa_key_id_t private_key_=0;
  uint64_t began_ms_=0, last_ms_=0;
  bool started_=false, exchanged_=false, consumed_=false, fault_=false;
};

}  // namespace stackchan::standalone

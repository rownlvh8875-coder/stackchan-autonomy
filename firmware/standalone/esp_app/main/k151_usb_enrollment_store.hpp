// SPDX-License-Identifier: MIT
// Dormant compile-only bridge: local physical permission -> verified NVS SWK1.
#pragma once
#include <atomic>
#include "consent_profile_store.hpp"
#include "k151_usb_scfg.hpp"
#include "nvs_port.hpp"

namespace stackchan::standalone {

class K151UsbEnrollmentStorage final {
 public:
  K151UsbEnrollmentStorage(IsolatedNvs& nvs,
                           const std::atomic_bool& physical_enrollment,
                           const std::atomic_bool& physical_stop)
      : nvs_(nvs), guard_(nvs), gate_(guard_, physical_enrollment,
          physical_stop, [this](bool allowed) {
            nvs_.set_local_write_approval(allowed);
          }) {
    nvs_.set_local_write_approval(false);
  }
  K151UsbEnrollmentStorage(const K151UsbEnrollmentStorage&) = delete;
  K151UsbEnrollmentStorage& operator=(const K151UsbEnrollmentStorage&) = delete;

  // Call only after init_without_erase(); READ ONLY, never provisions a ledger.
  ProfileLoad inspect_profile() { return guard_.restore_profile(); }

  EnrollmentServer::ProfileStore profile_store() {
    return [this](std::span<const uint8_t> bytes) {
      return gate_.persist(bytes);
    };
  }

  static const char* compiled_link_marker();

 private:
  IsolatedNvs& nvs_;
  PersistentGuard guard_;
  ConsentProfileStore gate_;
};

}  // namespace stackchan::standalone

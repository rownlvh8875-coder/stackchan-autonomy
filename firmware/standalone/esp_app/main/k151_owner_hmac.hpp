// SPDX-License-Identifier: MIT
#pragma once

#include "saved_owner_credentials.hpp"

namespace stackchan::standalone {

// Uses a previously provisioned, reviewed ESP32-S3 HMAC_UP slot. The
// implementation never reads raw eFuse key bytes or changes the security state.
class K151OwnerHmac final : public OwnerCredentialCipher {
 public:
  explicit K151OwnerHmac(std::uint8_t slot) : slot_(slot) {}
  static bool available(std::uint8_t slot);
  bool seal(Plaintext plaintext, MutableRecord record) override;
  bool open(Record record, MutablePlaintext plaintext) override;

 private:
  const std::uint8_t slot_;
};

} // namespace stackchan::standalone

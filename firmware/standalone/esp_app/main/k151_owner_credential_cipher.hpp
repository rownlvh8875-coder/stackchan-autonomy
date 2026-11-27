// SPDX-License-Identifier: MIT
#pragma once

#include "saved_owner_credentials.hpp"
#include <psa/crypto.h>

namespace stackchan::standalone {

// Borrows a purpose-bound AES key already opened by a verified local key
// provider. This adapter neither creates persistent keys nor provisions eFuses.
class K151OwnerCredentialCipher final : public OwnerCredentialCipher {
 public:
  explicit K151OwnerCredentialCipher(psa_key_id_t key) : key_(key) {}
  bool seal(Plaintext plaintext, MutableRecord record) override;
  bool open(Record record, MutablePlaintext plaintext) override;
  static const char* compiled_link_marker();

 private:
  bool usable_key() const;
  psa_key_id_t key_;
};

} // namespace stackchan::standalone

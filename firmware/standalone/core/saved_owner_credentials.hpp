// SPDX-License-Identifier: MIT
#pragma once

#include "network_time_guard.hpp"
#include "persistent_store.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace stackchan::standalone {

enum class SavedSetupLoad { missing, restored, unusable };

// A board-local key provider must supply authenticated encryption with a
// distinct key for this version/purpose. A board identity is not a key.
class OwnerCredentialCipher {
 public:
  static constexpr size_t kSsidBytes = 32, kPassphraseBytes = 64, kApiKeyBytes = 220;
  static constexpr size_t kPlainBytes = 3 + kSsidBytes + kPassphraseBytes + kApiKeyBytes;
  static constexpr size_t kNonceBytes = 12, kTagBytes = 16;
  static constexpr size_t kSealedBytes = kNonceBytes + kPlainBytes + kTagBytes;
  using Plaintext = std::span<const uint8_t, kPlainBytes>;
  using MutablePlaintext = std::span<uint8_t, kPlainBytes>;
  using Record = std::span<const uint8_t, kSealedBytes>;
  using MutableRecord = std::span<uint8_t, kSealedBytes>;
  virtual ~OwnerCredentialCipher() = default;
  // seal supplies a fresh nonce; open authenticates it and the ciphertext.
  virtual bool seal(Plaintext plaintext, MutableRecord record) = 0;
  virtual bool open(Record record, MutablePlaintext plaintext) = 0;
};

class SavedOwnerCredentials final {
  static constexpr std::array<uint8_t, 4> kMagic{'K', 'C', 'R', '1'};

 public:
  static constexpr std::string_view kKey = "owner_cfg_v1";
  static constexpr size_t kRecordBytes = kMagic.size() + OwnerCredentialCipher::kSealedBytes;
  static bool has_record_envelope(std::span<const uint8_t> bytes) {
    return bytes.size() == kRecordBytes && std::equal(kMagic.begin(), kMagic.end(), bytes.begin());
  }
  SavedOwnerCredentials(AtomicKv& storage, OwnerCredentialCipher& cipher)
      : storage_(storage), cipher_(cipher) {}

  SavedSetupLoad restore(RuntimeSecrets& output) {
    if (output.valid()) return SavedSetupLoad::unusable;
    const auto saved = storage_.read(kKey, kRecordBytes);
    if (saved.code == ReadCode::missing && saved.bytes.empty()) return SavedSetupLoad::missing;
    if (saved.code != ReadCode::found || !has_record_envelope(saved.bytes))
      return SavedSetupLoad::unusable;
    PlainBuffer plain;
    if (!cipher_.open(OwnerCredentialCipher::Record(
            saved.bytes.data() + kMagic.size(), OwnerCredentialCipher::kSealedBytes),
                      plain.bytes)) return SavedSetupLoad::unusable;
    const auto& bytes = plain.bytes;
    const size_t ssid_n = bytes[0], pass_n = bytes[1], api_n = bytes[2];
    if (ssid_n > OwnerCredentialCipher::kSsidBytes || pass_n > OwnerCredentialCipher::kPassphraseBytes ||
        api_n > OwnerCredentialCipher::kApiKeyBytes) return SavedSetupLoad::unusable;
    const auto* ssid = bytes.data() + 3;
    const auto* pass = reinterpret_cast<const char*>(ssid + ssid_n);
    const auto* api = pass + pass_n;
    const bool valid = output.provision({ssid, ssid_n}, {pass, pass_n}, {api, api_n}, true);
    return valid ? SavedSetupLoad::restored : SavedSetupLoad::unusable;
  }

  // Single-owner task, explicit first save. An uncertain or existing record
  // requires a separate recovery/rotation flow and is never overwritten here.
  template<class Authorized>
  bool save_first(const RuntimeSecrets& setup, Authorized authorized) {
    if (!setup.valid() || !authorized()) return false;
    const auto existing = storage_.read(kKey, kRecordBytes);
    if (existing.code != ReadCode::missing || !existing.bytes.empty() || !authorized()) return false;
    const auto ssid = setup.ssid();
    const auto pass = setup.passphrase();
    const auto api = setup.api_key();
    PlainBuffer plain;
    plain.bytes[0] = static_cast<uint8_t>(ssid.size());
    plain.bytes[1] = static_cast<uint8_t>(pass.size());
    plain.bytes[2] = static_cast<uint8_t>(api.size());
    auto next = std::copy(ssid.begin(), ssid.end(), plain.bytes.begin() + 3);
    next = std::copy(pass.begin(), pass.end(), next);
    std::copy(api.begin(), api.end(), next);
    std::array<uint8_t, kRecordBytes> record{};
    std::copy(kMagic.begin(), kMagic.end(), record.begin());
    if (!cipher_.seal(plain.bytes, OwnerCredentialCipher::MutableRecord(
            record.data() + kMagic.size(), OwnerCredentialCipher::kSealedBytes)) ||
        !authorized() || !storage_.commit(kKey, record) || !authorized()) return false;
    const auto observed = storage_.read(kKey, kRecordBytes);
    return observed.code == ReadCode::found && std::ranges::equal(record, observed.bytes) &&
           authorized();
  }

 private:
  struct PlainBuffer {
    std::array<uint8_t, OwnerCredentialCipher::kPlainBytes> bytes{};
    ~PlainBuffer() { wipe_secret(bytes.data(), bytes.size()); }
  };

  AtomicKv& storage_;
  OwnerCredentialCipher& cipher_;
};

} // namespace stackchan::standalone

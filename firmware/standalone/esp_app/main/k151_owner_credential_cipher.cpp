// SPDX-License-Identifier: MIT
#include "k151_owner_credential_cipher.hpp"

namespace stackchan::standalone {
namespace {
constexpr uint8_t kContext[] = {
  'K', '1', '5', '1', ':', 'o', 'w', 'n', 'e', 'r', '_', 'c', 'f', 'g', '_', 'v', '1'
};
constexpr auto kAlgorithm = PSA_ALG_GCM;
constexpr auto kRequiredUsage = PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT;
}

bool K151OwnerCredentialCipher::usable_key() const {
  if (psa_crypto_init() != PSA_SUCCESS) return false;
  psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
  const auto status = psa_get_key_attributes(key_, &attributes);
  const auto usage = psa_get_key_usage_flags(&attributes);
  const bool usable = status == PSA_SUCCESS &&
      psa_get_key_type(&attributes) == PSA_KEY_TYPE_AES &&
      psa_get_key_bits(&attributes) == 256 &&
      psa_get_key_algorithm(&attributes) == kAlgorithm &&
      (usage & kRequiredUsage) == kRequiredUsage &&
      !(usage & (PSA_KEY_USAGE_EXPORT | PSA_KEY_USAGE_COPY));
  psa_reset_key_attributes(&attributes);
  return usable;
}

bool K151OwnerCredentialCipher::seal(Plaintext plaintext, MutableRecord record) {
  size_t written = 0;
  auto ciphertext = record.subspan<kNonceBytes>();
  return usable_key() && psa_generate_random(record.data(), kNonceBytes) == PSA_SUCCESS &&
      psa_aead_encrypt(key_, kAlgorithm, record.data(), kNonceBytes, kContext, sizeof(kContext),
          plaintext.data(), plaintext.size(), ciphertext.data(), ciphertext.size(), &written) ==
      PSA_SUCCESS && written == ciphertext.size();
}

bool K151OwnerCredentialCipher::open(Record record, MutablePlaintext plaintext) {
  size_t written = 0;
  const auto ciphertext = record.subspan<kNonceBytes>();
  const bool authenticated = usable_key() &&
      psa_aead_decrypt(key_, kAlgorithm, record.data(), kNonceBytes, kContext, sizeof(kContext),
          ciphertext.data(), ciphertext.size(), plaintext.data(), plaintext.size(), &written) ==
      PSA_SUCCESS && written == plaintext.size();
  if (!authenticated) wipe_secret(plaintext.data(), plaintext.size());
  return authenticated;
}

const char* K151OwnerCredentialCipher::compiled_link_marker() {
  auto* volatile link = +[](K151OwnerCredentialCipher& cipher, MutablePlaintext plain,
                            MutableRecord record, bool sealing) {
    return sealing ? cipher.K151OwnerCredentialCipher::seal(plain, record)
                   : cipher.K151OwnerCredentialCipher::open(record, plain);
  };
  (void)link;
  return "K151 saved-setup cipher linked; no key opened";
}

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
#include "k151_owner_hmac.hpp"
#include "k151_owner_credential_cipher.hpp"

#include <bootloader_random.h>
#include <esp_efuse.h>
#include <esp_efuse_table.h>
#include <esp_flash_encrypt.h>
#include <esp_secure_boot.h>
#include <psa_crypto_driver_esp_hmac_opaque.h>
#include <sdkconfig.h>

namespace stackchan::standalone {
namespace {
constexpr char kDerivationLabel[] = "StackChan K151 owner_cfg_v1 AES-256-GCM";
constexpr auto kHmac = PSA_ALG_HMAC(PSA_ALG_SHA_256);

struct VolatileKey {
  psa_key_id_t id = 0;
  ~VolatileKey() { (void)destroy(); }
  bool destroy() {
    if (id == 0) return true;
    if (psa_destroy_key(id) != PSA_SUCCESS) return false;
    id = 0;
    return true;
  }
};

struct DerivedKeyBytes {
  std::array<std::uint8_t, 32> bytes{};
  ~DerivedKeyBytes() { wipe_secret(bytes.data(), bytes.size()); }
};

bool derive_cipher_key(std::uint8_t slot, VolatileKey& aes) {
  if (!K151OwnerHmac::available(slot) || psa_crypto_init() != PSA_SUCCESS) return false;
  VolatileKey hmac;
  psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
  psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_SIGN_MESSAGE);
  psa_set_key_algorithm(&attributes, kHmac);
  psa_set_key_type(&attributes, PSA_KEY_TYPE_HMAC);
  psa_set_key_bits(&attributes, 256);
  psa_set_key_lifetime(&attributes, PSA_KEY_LIFETIME_ESP_HMAC_VOLATILE);
  const esp_hmac_opaque_key_t reference{.efuse_key_id = slot};
  const auto imported = psa_import_key(&attributes,
      reinterpret_cast<const std::uint8_t*>(&reference), sizeof(reference), &hmac.id);
  psa_reset_key_attributes(&attributes);
  if (imported != PSA_SUCCESS) return false;

  DerivedKeyBytes material;
  std::size_t written = 0;
  const auto result = psa_mac_compute(hmac.id, kHmac,
      reinterpret_cast<const std::uint8_t*>(kDerivationLabel), sizeof(kDerivationLabel) - 1,
      material.bytes.data(), material.bytes.size(), &written);
  if (!hmac.destroy() || result != PSA_SUCCESS || written != material.bytes.size()) return false;

  psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
  psa_set_key_algorithm(&attributes, PSA_ALG_GCM);
  psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
  psa_set_key_bits(&attributes, 256);
  psa_set_key_lifetime(&attributes, PSA_KEY_LIFETIME_VOLATILE);
  const auto aes_import = psa_import_key(&attributes, material.bytes.data(), material.bytes.size(),
                                        &aes.id);
  psa_reset_key_attributes(&attributes);
  return aes_import == PSA_SUCCESS;
}
}

bool K151OwnerHmac::available(std::uint8_t slot) {
#if defined(CONFIG_EFUSE_VIRTUAL) || defined(CONFIG_NVS_ENCRYPTION)
  // The reviewed layout uses application-layer encryption and no NVS key partition.
  (void)slot;
  return false;
#else
  if (slot >= 6 || !esp_secure_boot_enabled() ||
      esp_get_flash_encryption_mode() != ESP_FLASH_ENC_MODE_RELEASE ||
      !esp_efuse_read_field_bit(ESP_EFUSE_DIS_PAD_JTAG) ||
      !esp_efuse_read_field_bit(ESP_EFUSE_DIS_USB_JTAG) ||
      !(esp_efuse_read_field_bit(ESP_EFUSE_DIS_DOWNLOAD_MODE) ||
        esp_efuse_read_field_bit(ESP_EFUSE_ENABLE_SECURITY_DOWNLOAD))) return false;
  const auto block = static_cast<esp_efuse_block_t>(EFUSE_BLK_KEY0 + slot);
  return esp_efuse_get_key_purpose(block) == ESP_EFUSE_KEY_PURPOSE_HMAC_UP &&
         esp_efuse_get_key_dis_read(block) && esp_efuse_get_key_dis_write(block) &&
         esp_efuse_get_keypurpose_dis_write(block);
#endif
}

bool K151OwnerHmac::seal(Plaintext plaintext, MutableRecord record) {
  VolatileKey aes;
  if (!derive_cipher_key(slot_, aes)) return false;
  // Initial save runs before Wi-Fi and before audio owns any peripheral.
  bootloader_random_enable();
  const bool encrypted = K151OwnerCredentialCipher(aes.id).seal(plaintext, record);
  bootloader_random_disable();
  return aes.destroy() && encrypted;
}

bool K151OwnerHmac::open(Record record, MutablePlaintext plaintext) {
  VolatileKey aes;
  const bool opened = derive_cipher_key(slot_, aes) &&
      K151OwnerCredentialCipher(aes.id).open(record, plaintext);
  if (aes.destroy() && opened) return true;
  wipe_secret(plaintext.data(), plaintext.size());
  return false;
}

} // namespace stackchan::standalone

// SPDX-License-Identifier: MIT
#include "k151_owner_code.hpp"
#include "k151_owner_credential_cipher.hpp"

#include <bootloader_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <sdkconfig.h>
#include <utility>

namespace stackchan::standalone {
namespace {
constexpr auto kAlgorithm = PSA_ALG_PBKDF2_HMAC(PSA_ALG_SHA_256);
constexpr uint64_t kIterations = 600'000; // owner_cfg_v2; changing this needs a new version.
constexpr char kPurpose[] = "StackChan K151 owner_cfg_v2 AES-256-GCM";
static_assert(kOwnerCodeAlphabet.size() == 32);
}

bool K151OwnerCode::available() {
#if defined(CONFIG_FREERTOS_UNICORE) || defined(CONFIG_NVS_ENCRYPTION) || \
    defined(CONFIG_EFUSE_VIRTUAL) || !defined(CONFIG_ESP_COREDUMP_ENABLE_TO_NONE)
  return false;
#else
  return true;
#endif
}

bool K151OwnerCode::generate(std::span<char, kOwnerCodeLength> output) {
  if (stop_.load() || state() != State::idle || psa_crypto_init() != PSA_SUCCESS) return false;
  K151OwnerCodeNvs::Salt salt{};
  std::array<uint8_t, kOwnerCodeLength> random{};
  // Called only in the boot owner task's hardware-entropy setup window.
  const bool generated = psa_generate_random(salt.data(), salt.size()) == PSA_SUCCESS &&
      psa_generate_random(random.data(), random.size()) == PSA_SUCCESS && storage_.prepare_salt(salt);
  if (generated)
    for (size_t i = 0; i < output.size(); ++i) output[i] = kOwnerCodeAlphabet[random[i] & 31];
  wipe_secret(random.data(), random.size());
  return generated && !stop_.load();
}

bool K151OwnerCode::begin(OwnerCode code) {
  if (!available() || stop_.load() || state() != State::idle || !storage_.has_salt() ||
      !std::ranges::all_of(code, [](char c) {
        return kOwnerCodeAlphabet.find(c) != std::string_view::npos;
      })) return false;
  std::copy(code.begin(), code.end(), code_.begin());
  state_.store(State::deriving);
  // Keep display/cancel polling on core 0. No board or UI port belongs to the worker.
  // Time-slice with core 1's idle task so its watchdog still runs.
  if (xTaskCreatePinnedToCore(task, "owner_unlock", 6144, this, tskIDLE_PRIORITY, nullptr, 1) == pdPASS)
    return true;
  wipe_secret(reinterpret_cast<unsigned char*>(code_.data()), code_.size());
  state_.store(State::failed);
  return false;
}

void K151OwnerCode::task(void* self) {
  static_cast<K151OwnerCode*>(self)->derive();
  vTaskDelete(nullptr);
}

void K151OwnerCode::derive() {
  psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
  psa_set_key_type(&attr, PSA_KEY_TYPE_PASSWORD);
  psa_set_key_algorithm(&attr, kAlgorithm);
  psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_DERIVE);
  psa_key_id_t password = 0, derived = 0;
  const bool imported = state() == State::deriving && !stop_.load() &&
      psa_crypto_init() == PSA_SUCCESS &&
      psa_import_key(&attr, reinterpret_cast<const uint8_t*>(code_.data()), code_.size(),
                     &password) == PSA_SUCCESS;
  wipe_secret(reinterpret_cast<unsigned char*>(code_.data()), code_.size());
  psa_reset_key_attributes(&attr);
  auto operation = psa_key_derivation_operation_init();
  const auto& salt = storage_.salt();
  psa_set_key_type(&attr, PSA_KEY_TYPE_AES);
  psa_set_key_bits(&attr, 256);
  psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
  psa_set_key_algorithm(&attr, PSA_ALG_GCM);
  const bool derived_ok = imported &&
      psa_key_derivation_setup(&operation, kAlgorithm) == PSA_SUCCESS &&
      psa_key_derivation_input_integer(&operation, PSA_KEY_DERIVATION_INPUT_COST, kIterations) == PSA_SUCCESS &&
      psa_key_derivation_input_bytes(&operation, PSA_KEY_DERIVATION_INPUT_SALT,
          reinterpret_cast<const uint8_t*>(kPurpose), sizeof(kPurpose) - 1) == PSA_SUCCESS &&
      psa_key_derivation_input_bytes(&operation, PSA_KEY_DERIVATION_INPUT_SALT,
                                    salt.data(), salt.size()) == PSA_SUCCESS &&
      psa_key_derivation_input_key(&operation, PSA_KEY_DERIVATION_INPUT_PASSWORD, password) == PSA_SUCCESS &&
      state() == State::deriving && !stop_.load() &&
      psa_key_derivation_output_key(&attr, &operation, &derived) == PSA_SUCCESS;
  const bool finished = psa_key_derivation_abort(&operation) == PSA_SUCCESS;
  const bool scrubbed = password == 0 || psa_destroy_key(password) == PSA_SUCCESS;
  psa_reset_key_attributes(&attr);
  key_ = derived;
  auto running = State::deriving;
  if (derived_ok && finished && scrubbed && !stop_.load() &&
      state_.compare_exchange_strong(running, State::ready)) return;
  if (derived) (void)psa_destroy_key(derived);
  state_.store(State::failed);
}

bool K151OwnerCode::clear_key() {
  if (state_.exchange(State::failed) != State::ready) return true;
  const auto key = std::exchange(key_, 0);
  return psa_destroy_key(key) == PSA_SUCCESS;
}

void K151OwnerCode::cancel() { (void)clear_key(); }

bool K151OwnerCode::seal(Plaintext plaintext, MutableRecord record) {
  if (stop_.load() || state() != State::ready) return false;
  bootloader_random_enable(); // Paid review is complete; WLAN and audio have not started.
  const bool sealed = K151OwnerCredentialCipher(key_).seal(plaintext, record);
  bootloader_random_disable();
  return clear_key() && sealed && !stop_.load();
}

bool K151OwnerCode::open(Record record, MutablePlaintext plaintext) {
  const bool opened = !stop_.load() && state() == State::ready &&
      K151OwnerCredentialCipher(key_).open(record, plaintext);
  if (clear_key() && opened && !stop_.load()) return true;
  wipe_secret(plaintext.data(), plaintext.size());
  return false;
}

} // namespace stackchan::standalone

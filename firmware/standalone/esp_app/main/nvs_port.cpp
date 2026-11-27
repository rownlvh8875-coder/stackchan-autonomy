// SPDX-License-Identifier: MIT
#include "nvs_port.hpp"
#include "saved_owner_credentials.hpp"
#include <nvs.h>
#include <nvs_flash.h>
#include <string>
#include <utility>

namespace stackchan::standalone {
namespace {
constexpr char kNamespace[] = "sc_gpt";
constexpr char kOwnerNamespace[] = "sc_owner";
constexpr char kOwnerCodeKey[] = "owner_cfg_v2";
constexpr std::array<uint8_t, 4> kOwnerCodeMagic{'K', 'C', 'P', '2'};
constexpr size_t kEnvelopePrefix = kOwnerCodeMagic.size() + K151OwnerCodeNvs::Salt{}.size();
constexpr size_t kEnvelopeSize = kEnvelopePrefix + SavedOwnerCredentials::kRecordBytes;
bool allowed_key(std::string_view key) {
  return key == "wake_profile" || key == "budget";
}
ReadValue read_blob(const char* space, const char* key, size_t max_bytes) {
  nvs_handle_t handle{};
  esp_err_t err = nvs_open(space, NVS_READONLY, &handle);
  if (err == ESP_ERR_NVS_NOT_FOUND) return {ReadCode::missing, {}};
  if (err != ESP_OK) return {ReadCode::failure, {}};
  size_t len = 0;
  err = nvs_get_blob(handle, key, nullptr, &len);
  if (err == ESP_ERR_NVS_NOT_FOUND) {
    nvs_close(handle);
    return {ReadCode::missing, {}};
  }
  if (err != ESP_OK || len == 0 || len > max_bytes) {
    nvs_close(handle);
    return {ReadCode::failure, {}};
  }
  std::vector<uint8_t> data(len);
  err = nvs_get_blob(handle, key, data.data(), &len);
  nvs_close(handle);
  if (err != ESP_OK || len != data.size()) return {ReadCode::failure, {}};
  return {ReadCode::found, std::move(data)};
}

bool write_owner_blob(const char* key, std::span<const uint8_t> bytes,
                      const std::atomic_bool& stop) {
  nvs_handle_t handle{};
  if (stop.load() || nvs_open(kOwnerNamespace, NVS_READWRITE, &handle) != ESP_OK)
    return false;
  // Finish an admitted set/commit as one update. STOP after set still denies Wi-Fi.
  const bool committed = !stop.load() &&
      nvs_set_blob(handle, key, bytes.data(), bytes.size()) == ESP_OK &&
      nvs_commit(handle) == ESP_OK;
  nvs_close(handle);
  return committed && !stop.load();
}
}

bool IsolatedNvs::init_without_erase() {
  // Unlike the manufacturer Hal::init, do not erase NVS on NO_FREE_PAGES or
  // NEW_VERSION_FOUND. Any error must keep all independent features disabled.
  initialized_ = nvs_flash_init() == ESP_OK;
  return initialized_;
}

ReadValue IsolatedNvs::read(std::string_view key, size_t max_bytes) {
  if (!initialized_ || !allowed_key(key) || max_bytes == 0 || max_bytes > 4096)
    return {ReadCode::failure, {}};
  const std::string k(key);
  return read_blob(kNamespace, k.c_str(), max_bytes);
}

bool IsolatedNvs::commit(std::string_view key, std::span<const uint8_t> bytes) {
  if (!initialized_ || !write_authorized(key) || bytes.empty() || bytes.size() > 4096) {
    return false;
  }
  const std::string k(key);
  nvs_handle_t handle{};
  const esp_err_t opened = nvs_open(kNamespace, NVS_READWRITE, &handle);
  if (opened != ESP_OK) return false;
  const esp_err_t set = write_authorized(key) ?
      nvs_set_blob(handle, k.c_str(), bytes.data(), bytes.size()) : ESP_ERR_INVALID_STATE;
  // Finish an already-admitted update even if authorization is withdrawn
  // during the SDK call. That attempt cannot authorize any paid dispatch.
  const esp_err_t committed = set == ESP_OK ? nvs_commit(handle) : set;
  nvs_close(handle);
  return committed == ESP_OK && write_authorized(key); // Read-back belongs to PersistentGuard.
}

bool IsolatedNvs::write_authorized(std::string_view key) const {
  if (key == "wake_profile") return approved_;
  return key == "budget" && owner_ && owner_->load() && paid_consent_->load() &&
         budget_writes_->load() && !stop_->load();
}

ReadValue K151SavedOwnerNvs::read(std::string_view key, size_t max_bytes) {
  if (stop_.load() || key != SavedOwnerCredentials::kKey ||
      max_bytes != SavedOwnerCredentials::kRecordBytes) return {ReadCode::failure, {}};
  if (!initialized_) initialized_ = nvs_flash_init() == ESP_OK;
  if (!initialized_ || stop_.load()) return {ReadCode::failure, {}};
  auto result = read_blob(kOwnerNamespace, SavedOwnerCredentials::kKey.data(), max_bytes);
  if (stop_.load() ||
      (result.code == ReadCode::found && !SavedOwnerCredentials::has_record_envelope(result.bytes)))
    return {ReadCode::failure, {}};
  return result;
}

bool K151SavedOwnerNvs::commit(std::string_view key, std::span<const uint8_t> bytes) {
  if (!SavedOwnerCredentials::has_record_envelope(bytes) ||
      read(key, SavedOwnerCredentials::kRecordBytes).code != ReadCode::missing || stop_.load())
    return false;
  return write_owner_blob(SavedOwnerCredentials::kKey.data(), bytes, stop_);
}

ReadValue K151OwnerCodeNvs::envelope() {
  if (stop_.load()) return {ReadCode::failure, {}};
  if (!initialized_) initialized_ = nvs_flash_init() == ESP_OK;
  if (!initialized_ || stop_.load()) return {ReadCode::failure, {}};
  auto result = read_blob(kOwnerNamespace, kOwnerCodeKey, kEnvelopeSize);
  if (stop_.load()) return {ReadCode::failure, {}};
  if (result.code != ReadCode::found) return result;
  const auto& bytes = result.bytes;
  if (bytes.size() != kEnvelopeSize ||
      !std::equal(kOwnerCodeMagic.begin(), kOwnerCodeMagic.end(), bytes.begin()) ||
      !SavedOwnerCredentials::has_record_envelope(std::span(bytes).subspan(kEnvelopePrefix)))
    return {ReadCode::failure, {}};
  return result;
}

ReadCode K151OwnerCodeNvs::inspect() {
  if (salt_ready_) return ReadCode::failure;
  const auto record = envelope();
  initial_ = record.code;
  if (initial_ == ReadCode::found) {
    std::copy_n(record.bytes.begin() + kOwnerCodeMagic.size(), salt_.size(), salt_.begin());
    salt_ready_ = true;
  }
  return initial_;
}

bool K151OwnerCodeNvs::prepare_salt(const Salt& salt) {
  if (initial_ != ReadCode::missing || salt_ready_ || stop_.load()) return false;
  salt_ = salt;
  salt_ready_ = true;
  return true;
}

ReadValue K151OwnerCodeNvs::read(std::string_view key, size_t max_bytes) {
  if (!salt_ready_ || key != SavedOwnerCredentials::kKey ||
      max_bytes != SavedOwnerCredentials::kRecordBytes) return {ReadCode::failure, {}};
  auto record = envelope();
  if (record.code != ReadCode::found) return record;
  if (!std::equal(salt_.begin(), salt_.end(), record.bytes.begin() + kOwnerCodeMagic.size()))
    return {ReadCode::failure, {}};
  record.bytes.erase(record.bytes.begin(), record.bytes.begin() + kEnvelopePrefix);
  return record;
}

bool K151OwnerCodeNvs::commit(std::string_view key, std::span<const uint8_t> bytes) {
  if (initial_ != ReadCode::missing || !SavedOwnerCredentials::has_record_envelope(bytes) ||
      read(key, SavedOwnerCredentials::kRecordBytes).code != ReadCode::missing || stop_.load())
    return false;
  std::array<uint8_t, kEnvelopeSize> record{};
  auto end = std::copy(kOwnerCodeMagic.begin(), kOwnerCodeMagic.end(), record.begin());
  end = std::copy(salt_.begin(), salt_.end(), end);
  std::copy(bytes.begin(), bytes.end(), end);
  return write_owner_blob(kOwnerCodeKey, record, stop_);
}

}  // namespace stackchan::standalone

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
  nvs_handle_t handle{};
  if (nvs_open(kOwnerNamespace, NVS_READWRITE, &handle) != ESP_OK) return false;
  // Finish an admitted set/commit as one update. STOP after set still denies Wi-Fi.
  const bool committed = !stop_.load() &&
      nvs_set_blob(handle, SavedOwnerCredentials::kKey.data(), bytes.data(), bytes.size()) == ESP_OK &&
      nvs_commit(handle) == ESP_OK;
  nvs_close(handle);
  return committed && !stop_.load();
}

}  // namespace stackchan::standalone

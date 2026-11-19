// SPDX-License-Identifier: MIT
#include "nvs_port.hpp"
#include <nvs.h>
#include <nvs_flash.h>
#include <string>
#include <utility>

namespace stackchan::standalone {
namespace {
constexpr char kNamespace[] = "sc_gpt";
bool allowed_key(std::string_view key) {
  return key == "wake_profile" || key == "budget";
}
}

bool IsolatedNvs::init_without_erase() {
  // Unlike the manufacturer Hal::init, do not erase NVS on NO_FREE_PAGES or
  // NEW_VERSION_FOUND. Any error must keep all independent features disabled.
  initialized_ = nvs_flash_init() == ESP_OK;
  return initialized_;
}

ReadValue IsolatedNvs::read(std::string_view key, size_t max_bytes) {
  if (!initialized_ || !allowed_key(key) || max_bytes == 0 || max_bytes > 4096) {
    return {ReadCode::failure, {}};
  }
  const std::string k(key);
  nvs_handle_t handle{};
  esp_err_t err = nvs_open(kNamespace, NVS_READONLY, &handle);
  if (err == ESP_ERR_NVS_NOT_FOUND) return {ReadCode::missing, {}};
  if (err != ESP_OK) return {ReadCode::failure, {}};
  size_t len = 0;
  err = nvs_get_blob(handle, k.c_str(), nullptr, &len);
  if (err == ESP_ERR_NVS_NOT_FOUND) {
    nvs_close(handle);
    return {ReadCode::missing, {}};
  }
  if (err != ESP_OK || len == 0 || len > max_bytes) {
    nvs_close(handle);
    return {ReadCode::failure, {}};
  }
  std::vector<uint8_t> data(len);
  err = nvs_get_blob(handle, k.c_str(), data.data(), &len);
  nvs_close(handle);
  if (err != ESP_OK || len != data.size()) return {ReadCode::failure, {}};
  return {ReadCode::found, std::move(data)};
}

bool IsolatedNvs::commit(std::string_view key, std::span<const uint8_t> bytes) {
  if (!initialized_ || !approved_ || !allowed_key(key) || bytes.empty() || bytes.size() > 4096) {
    return false;
  }
  const std::string k(key);
  nvs_handle_t handle{};
  const esp_err_t opened = nvs_open(kNamespace, NVS_READWRITE, &handle);
  if (opened != ESP_OK) return false;
  const esp_err_t set = nvs_set_blob(handle, k.c_str(), bytes.data(), bytes.size());
  const esp_err_t committed = set == ESP_OK ? nvs_commit(handle) : set;
  nvs_close(handle);
  return committed == ESP_OK; // Persistence guard independently reads back.
}

}  // namespace stackchan::standalone

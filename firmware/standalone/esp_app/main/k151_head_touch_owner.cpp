// SPDX-License-Identifier: MIT
#include "k151_head_touch_owner.hpp"
#include "k151_owner_setup.hpp"

#include <array>
#include <esp_err.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
constexpr uint16_t kSi12tAddress = 0x68; // Factory Si12T_GND_ADDRESS
constexpr uint8_t kTouchResultRegister = 0x10; // SI12T_OUTPUT1_ADDR
constexpr uint32_t kBusRateHz = 100000;
constexpr int kI2cTimeoutMs = 100;
constexpr unsigned kSettleMs = 200; // M5Stack's post-setup boot delay.
}

const char* K151HeadTouchOwner::compiled_link_marker() {
  auto volatile attach = &K151HeadTouchOwner::attach_for_setup;
  (void)attach;
  return "Si12T head touch physical-presence adapter linked; NOT STARTED";
}

K151HeadTouchOwner::~K151HeadTouchOwner() { (void)detach(); }

bool K151HeadTouchOwner::attach_readonly(i2c_master_bus_handle_t borrowed_bus,
                                        bool board_identity_verified,
                                        bool sensor_preinitialized,
                                        bool exclusive_bus_control,
                                        uint64_t monotonic_ms) {
  if (!sensor_preinitialized ||
      !attach_device(borrowed_bus, board_identity_verified, exclusive_bus_control))
    return false;
  if (!gesture_.begin(true, monotonic_ms)) return failed();
  return true;
}

bool K151HeadTouchOwner::attach_for_setup(i2c_master_bus_handle_t borrowed_bus,
                                         bool board_identity_verified,
                                         bool exclusive_bus_control) {
  const auto start_us = esp_timer_get_time();
  if (start_us < 0 ||
      !attach_device(borrowed_bus, board_identity_verified, exclusive_bus_control))
    return false;
  if (!configure_pads()) return failed();
  const auto ready_us = esp_timer_get_time();
  if (stop_.load() || ready_us < start_us ||
      !gesture_.begin(true, static_cast<uint64_t>(ready_us / 1000))) return failed();
  return true;
}

bool K151HeadTouchOwner::attach_device(i2c_master_bus_handle_t bus,
                                      bool board_verified,
                                      bool exclusive_bus_control) {
  i2c_master_bus_handle_t registered = nullptr;
  if (attempted_ || !bus || !board_verified || !exclusive_bus_control ||
      stop_.load() || i2c_master_get_bus_handle(I2C_NUM_1, &registered) != ESP_OK ||
      registered != bus || stop_.load()) return false;
  attempted_ = true;
  i2c_device_config_t cfg = {};
  cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  cfg.device_address = kSi12tAddress;
  cfg.scl_speed_hz = kBusRateHz;
  if (i2c_master_bus_add_device(bus, &cfg, &dev_) != ESP_OK || stop_.load())
    return failed();
  return true;
}

bool K151HeadTouchOwner::read_register(uint8_t reg, uint8_t& value) const {
  return i2c_master_transmit_receive(dev_, &reg, 1, &value, 1, kI2cTimeoutMs) == ESP_OK;
}

bool K151HeadTouchOwner::write_register(uint8_t reg, uint8_t value) const {
  const uint8_t bytes[]{reg, value};
  return i2c_master_transmit(dev_, bytes, sizeof(bytes), kI2cTimeoutMs) == ESP_OK;
}

bool K151HeadTouchOwner::read_setup_mode() const {
  uint8_t config{}, control{};
  // Both values match the documented reset state and M5Stack's ready state.
  // Leave unknown modes alone, including a sensor held in software reset.
  return !stop_.load() && read_register(0x08, config) && config == 0x22 &&
         !stop_.load() && read_register(0x09, control) && control == 0x07 &&
         !stop_.load();
}

bool K151HeadTouchOwner::configure_pads() {
  if (!read_setup_mode()) return false;
  for (size_t i = 0; i < kPadFields.size(); ++i) {
    if (stop_.load() || !read_register(kPadFields[i].reg, original_[i])) return false;
  }
  bool needs_settle = false;
  for (size_t i = 0; i < kPadFields.size(); ++i) {
    if (stop_.load()) return false;
    const auto [reg, mask, required] = kPadFields[i];
    const auto desired = static_cast<uint8_t>((original_[i] & ~mask) | required);
    if (desired == original_[i]) continue;
    // A transfer error can be reported after the peripheral received the write.
    changed_[i] = true;
    needs_settle = true;
    uint8_t actual{};
    if (!write_register(reg, desired) || stop_.load() ||
        !read_register(reg, actual) || actual != desired) return false;
  }
  if (!needs_settle) return !stop_.load();
  if (stop_.load()) return false;
  vTaskDelay(pdMS_TO_TICKS(kSettleMs) + 1);
  if (!read_setup_mode()) return false;
  // A brownout during settling can return the device to its default settings.
  for (const auto [reg, mask, required] : kPadFields) {
    uint8_t actual{};
    if (stop_.load() || !read_register(reg, actual) || (actual & mask) != required)
      return false;
  }
  return !stop_.load();
}

bool K151HeadTouchOwner::restore_pads() {
  for (size_t i = kPadFields.size(); i-- > 0;) {
    if (!changed_[i]) continue;
    const auto [reg, mask, required] = kPadFields[i];
    uint8_t current{};
    if (!read_register(reg, current)) return false;
    const auto desired = static_cast<uint8_t>((current & ~mask) | (original_[i] & mask));
    if (desired != current &&
        (!write_register(reg, desired) || !read_register(reg, current) || current != desired))
      return false;
    changed_[i] = false;
  }
  return true;
}

TouchConsentEvent K151HeadTouchOwner::poll_once(uint64_t monotonic_ms) {
  last_read_failed_ = false;
  if (stop_.load()) {
    (void)detach();
    return TouchConsentEvent::invalidated;
  }
  if (faulted_ || !dev_) return TouchConsentEvent::none;
  uint8_t packed = 0;
  const esp_err_t result = i2c_master_transmit_receive(
      dev_, &kTouchResultRegister, 1, &packed, 1, kI2cTimeoutMs);
  last_read_failed_ = result != ESP_OK;
  const std::array<uint8_t,3> pads = {
      static_cast<uint8_t>(packed & 0x03U),
      static_cast<uint8_t>((packed >> 2U) & 0x03U),
      static_cast<uint8_t>((packed >> 4U) & 0x03U)};
  const auto event = gesture_.sample(pads, monotonic_ms, result == ESP_OK,
                                    stop_.load());
  if (event == TouchConsentEvent::owner_window_open && !stop_.load()) {
    owner_mode_.store(true, std::memory_order_release);
  } else if (event == TouchConsentEvent::invalidated || stop_.load()) {
    (void)failed();
  }
  // This never returns touch-derived Wi-Fi passwords or authentication data.
  return event;
}

bool K151HeadTouchOwner::begin_owner_setup(
    K151LocalOwnerSetup& setup, bool trusted_local_ui, uint64_t now_ms) {
  return trusted_local_ui && owner_window_open(now_ms) && setup.arm(now_ms);
}

bool K151HeadTouchOwner::request_final_confirmation(
    K151LocalOwnerSetup& setup, bool trusted_local_reviewed, uint64_t now_ms) {
  return trusted_local_reviewed && owner_window_open(now_ms) &&
         setup.phase() == OwnerSetupPhase::confirm &&
         gesture_.request_final_confirmation(true, now_ms);
}

bool K151HeadTouchOwner::finish_owner_setup(K151LocalOwnerSetup& setup,
                                            uint64_t now_ms) {
  if (faulted_ || stop_.load() || !owner_window_open(now_ms) ||
      setup.phase() != OwnerSetupPhase::confirm ||
      !gesture_.take_final_confirmation(now_ms, stop_.load())) return false;
  // The physical token is spent BEFORE the RAM-only credential commit.
  return setup.confirm(now_ms, true);
}

bool K151HeadTouchOwner::owner_window_open(uint64_t now_ms) const {
  return !faulted_ && !stop_.load() && owner_mode_.load() &&
         gesture_.owner_window_open(now_ms);
}

bool K151HeadTouchOwner::start_scps_final_touch(
    bool trusted_local_reviewed,uint64_t now_ms) {
  return trusted_local_reviewed && owner_window_open(now_ms) &&
         gesture_.request_final_confirmation(true,now_ms);
}

bool K151HeadTouchOwner::take_scps_final_touch(uint64_t now_ms) {
  return owner_window_open(now_ms) &&
         gesture_.take_final_confirmation(now_ms,stop_.load());
}

bool K151HeadTouchOwner::failed() {
  faulted_ = true;
  (void)detach();
  return false;
}

void K151HeadTouchOwner::revoke() {
  owner_mode_.store(false, std::memory_order_release);
  (void)gesture_.stop();
}

bool K151HeadTouchOwner::detach() {
  revoke();
  if (!dev_) return true;
  if (!restore_pads() || i2c_master_bus_rm_device(dev_) != ESP_OK) {
    faulted_ = true;
    return false;
  }
  dev_ = nullptr;
  return true;
}

}  // namespace stackchan::standalone

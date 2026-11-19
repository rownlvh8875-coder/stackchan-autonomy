// SPDX-License-Identifier: MIT
// Read ONLY the Si12T touch-result register; deliberately do NOT call the
// manufacturer's si12t_setup() (writes calibration and control registers).
#include "k151_head_touch_owner.hpp"
#include "k151_owner_setup.hpp"

#include <array>
#include <esp_err.h>

namespace stackchan::standalone {
namespace {
constexpr uint16_t kSi12tAddress = 0x68; // Factory Si12T_GND_ADDRESS
constexpr uint8_t kTouchResultRegister = 0x10; // SI12T_OUTPUT1_ADDR
constexpr uint32_t kBusRateHz = 100000;
constexpr int kI2cTimeoutMs = 100;
}

const char* K151HeadTouchOwner::compiled_link_marker() {
  return "Si12T head touch physical-presence adapter linked; NOT STARTED";
}

K151HeadTouchOwner::~K151HeadTouchOwner() { revoke(); (void)detach_readonly(); }

bool K151HeadTouchOwner::attach_readonly(i2c_master_bus_handle_t borrowed_bus,
                                        bool board_identity_verified,
                                        bool sensor_preinitialized,
                                        bool exclusive_bus_control,
                                        uint64_t monotonic_ms) {
  if (attempted_ || !borrowed_bus || !board_identity_verified ||
      !sensor_preinitialized || !exclusive_bus_control || stop_.load()) return false;
  attempted_ = true;
  i2c_device_config_t cfg = {};
  cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  cfg.device_address = kSi12tAddress;
  cfg.scl_speed_hz = kBusRateHz;
  if (i2c_master_bus_add_device(borrowed_bus, &cfg, &dev_) != ESP_OK)
    return failed();
  if (!gesture_.begin(true, monotonic_ms)) return failed();
  return true;
}

TouchConsentEvent K151HeadTouchOwner::poll_once(uint64_t monotonic_ms) {
  if (stop_.load()) {
    revoke();
    return TouchConsentEvent::invalidated;
  }
  if (faulted_ || !dev_) return TouchConsentEvent::none;
  uint8_t packed = 0;
  const esp_err_t result = i2c_master_transmit_receive(
      dev_, &kTouchResultRegister, 1, &packed, 1, kI2cTimeoutMs);
  const std::array<uint8_t,3> pads = {
      static_cast<uint8_t>(packed & 0x03U),
      static_cast<uint8_t>((packed >> 2U) & 0x03U),
      static_cast<uint8_t>((packed >> 4U) & 0x03U)};
  const auto event = gesture_.sample(pads, monotonic_ms, result == ESP_OK,
                                    stop_.load());
  if (event == TouchConsentEvent::owner_window_open && !stop_.load()) {
    owner_mode_.store(true, std::memory_order_release);
  } else if (event == TouchConsentEvent::invalidated || stop_.load()) {
    owner_mode_.store(false, std::memory_order_release);
    faulted_ = true;
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
  revoke();
  return false;
}

void K151HeadTouchOwner::revoke() {
  owner_mode_.store(false, std::memory_order_release);
  (void)gesture_.stop();
}

bool K151HeadTouchOwner::detach_readonly() {
  if (!dev_) return !faulted_;
  const esp_err_t result = i2c_master_bus_rm_device(dev_);
  if (result == ESP_OK) dev_ = nullptr;
  else faulted_ = true;
  return result == ESP_OK && !faulted_;
}

}  // namespace stackchan::standalone

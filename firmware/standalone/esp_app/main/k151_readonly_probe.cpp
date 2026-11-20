// SPDX-License-Identifier: MIT
// K151 I2C read-only probe, linked but NOT called in app_main.
#include "k151_readonly_probe.hpp"
#include "k151_contract.hpp"
#include <array>
#include <cstdint>
#include <driver/i2c_master.h>
#include <esp_codec_dev_defaults.h>

namespace stackchan::standalone {
namespace {
constexpr int kTimeoutMs = 30;
constexpr uint32_t kI2cSpeedHz = 100000;
constexpr uint8_t kTouchVersionReg = 0xA3;
constexpr std::array<uint16_t, 5> kAddresses = {
    0x34, 0x58, 0x38, ES7210_CODEC_DEFAULT_ADDR, AW88298_CODEC_DEFAULT_ADDR};
}  // namespace

const char* K151ReadOnlyProbe::compiled_link_marker() {
  return "K151 I2C diagnostic present; no startup bus/power/device access";
}

bool K151ReadOnlyProbe::observe_once(bool explicitly_authorized,
                                    const std::atomic_bool& stop,
                                    k151::ReadOnlyEvidence& out) const {
  out = {};
  if (!explicitly_authorized || stop.load()) return false;
  // Creating the master bus DOES change GPIO muxing, even though the probe
  // does not update device registers. Never call from the shipping HOLD app.
  i2c_master_bus_handle_t bus = nullptr;
  i2c_master_bus_config_t cfg = {};
  cfg.i2c_port = I2C_NUM_1;
  cfg.sda_io_num = static_cast<gpio_num_t>(k151::kI2cSda);
  cfg.scl_io_num = static_cast<gpio_num_t>(k151::kI2cScl);
  cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  cfg.glitch_ignore_cnt = 7;
  cfg.flags.enable_internal_pullup = 1;
  if (i2c_new_master_bus(&cfg, &bus) != ESP_OK) return false;
  out.bus_opened = true;
  bool ok = true;
  for (size_t i = 0; i < kAddresses.size(); ++i) {
    if (stop.load()) { ok = false; break; }
    const esp_err_t result = i2c_master_probe(bus, kAddresses[i], kTimeoutMs);
    if (result == ESP_OK) {
      out.acknowledged[i] = true;
    } else if (result != ESP_ERR_NOT_FOUND) {
      ok = false;
      break;
    }
  }
  if (ok && !stop.load() &&
      out.acknowledged[k151::index(k151::Device::touch_ft6336)]) {
    i2c_device_config_t device_cfg = {};
    device_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    device_cfg.device_address = 0x38;
    device_cfg.scl_speed_hz = kI2cSpeedHz;
    i2c_master_dev_handle_t dev = nullptr;
    if (i2c_master_bus_add_device(bus, &device_cfg, &dev) == ESP_OK) {
      // An address-only register-pointer transmission plus a read; does NOT
      // send the manufacturer's work-mode configuration write {0x00,0x00}.
      // It may not yield a valid version; never assume the LCD is type C.
      const esp_err_t read = i2c_master_transmit_receive(
          dev, &kTouchVersionReg, 1, out.touch_version.data(),
          out.touch_version.size(), kTimeoutMs);
      out.touch_version_read = read == ESP_OK;
      if (i2c_master_bus_rm_device(dev) != ESP_OK) ok = false;
    } else {
      ok = false;
    }
  }
  if (stop.load()) ok = false;
  if (i2c_del_master_bus(bus) != ESP_OK) ok = false;
  out.finished_without_bus_error = ok;
  return ok;
}
}  // namespace stackchan::standalone

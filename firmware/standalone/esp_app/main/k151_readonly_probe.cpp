// SPDX-License-Identifier: MIT
// Fixed read-only observer. Never called by the HOLD application.
#include "k151_readonly_probe.hpp"
#include "k151_contract.hpp"
#include <driver/i2c_master.h>
#include <type_traits>

namespace stackchan::standalone {
namespace {
constexpr int kTimeoutMs = 30;
constexpr uint32_t kI2cSpeedHz = 100000;
constexpr uint8_t kTouchVersionReg = 0xA3;
using k151::Device;
using k151::PowerSample;

bool read_pmic_power(auto read, k151::PowerReadback& result) {
  uint8_t id{}, channels{};
  if (!read(0x03, &id, 1)) return false;
  if (id != 0x4a) {
    result.pmic_vsys = PowerSample::id_mismatch;
    return true;
  }
  if (!read(0x30, &channels, 1)) return false;
  if (!(channels & (1 << 3))) {
    result.pmic_vsys = PowerSample::disabled;
    return true;
  }
  std::array<uint8_t, 2> data{};
  // X-Powers requires a high-byte-first read for the ADC.
  if (!read(0x3a, data.data(), data.size())) return false;
  const unsigned code = (unsigned(data[0]) << 8) | data[1];
  if (!code || code > 0x3fff) {
    result.pmic_vsys = PowerSample::invalid;
  } else {
    result.pmic_vsys = PowerSample::sampled;
    result.pmic_vsys_mv = static_cast<uint16_t>(code); // 1 mV/LSB.
  }
  return true;
}

bool read_amp_power(auto read, k151::PowerReadback& result) {
  std::array<uint8_t, 2> data{};
  const auto word = [&] { return (unsigned(data[0]) << 8) | data[1]; };
  if (!read(0x00, data.data(), data.size())) return false;
  if (word() != 0x1852) {
    result.amp_vdd = PowerSample::id_mismatch;
    return true;
  }
  if (!read(0x04, data.data(), data.size())) return false;
  if (word() & 1) { // SYSCTRL.PWDN: do not wake the amp to obtain a reading.
    result.amp_vdd = PowerSample::powered_down;
    return true;
  }
  if (!read(0x01, data.data(), data.size())) return false; // SYSST, never SYSINT.
  result.amp_uvls_valid = true;
  result.amp_uvls = (word() & (1 << 14)) != 0;
  if (!read(0x12, data.data(), data.size())) return false;
  const auto code = word();
  if (!code || code > 0x3ff) {
    result.amp_vdd = PowerSample::invalid;
  } else if (code == 0x263) {
    result.amp_vdd = PowerSample::reset_value;
  } else {
    result.amp_vdd = PowerSample::sampled;
    result.amp_vdd_mv = static_cast<uint16_t>((code * 6025 + 511) / 1023);
  }
  return true;
}

template <typename Evidence>
bool observe(const std::atomic_bool& owner, const std::atomic_bool& stop, Evidence& out) {
  constexpr bool power_only = std::is_same_v<Evidence, k151::PowerReadback>;
  out = {};
  Evidence candidate{};
  std::array<bool, k151::kProbeAddresses.size()> acknowledged{};
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (!allowed()) return false;
  // Opening the master bus changes GPIO muxing. Requires separate hardware
  // approval, even though no device-configuration register is written.
  i2c_master_bus_handle_t bus = nullptr;
  i2c_master_bus_config_t cfg = {};
  cfg.i2c_port = I2C_NUM_1;
  cfg.sda_io_num = static_cast<gpio_num_t>(k151::kI2cSda);
  cfg.scl_io_num = static_cast<gpio_num_t>(k151::kI2cScl);
  cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  cfg.glitch_ignore_cnt = 7;
  cfg.flags.enable_internal_pullup = 1;
  if (i2c_new_master_bus(&cfg, &bus) != ESP_OK) return false;
  bool ok = allowed();
  for (size_t i = 0; ok && i < k151::kProbeAddresses.size(); ++i) {
    if (power_only && i != k151::index(Device::pmic_axp2101) &&
        i != k151::index(Device::amp_aw88298)) continue;
    if (!allowed()) { ok = false; break; }
    const esp_err_t result = i2c_master_probe(bus, k151::kProbeAddresses[i], kTimeoutMs);
    ok = allowed() && (result == ESP_OK || result == ESP_ERR_NOT_FOUND);
    if (ok) acknowledged[i] = result == ESP_OK;
  }
  const auto read = [&](i2c_master_dev_handle_t dev, uint8_t reg,
                        uint8_t* data, size_t bytes) {
    if (!allowed()) return false;
    // Exactly one register-pointer byte, followed by a repeated-start read.
    // Never sends a configuration value, reset, or touch work-mode write.
    const auto result = i2c_master_transmit_receive(dev, &reg, 1, data, bytes, kTimeoutMs);
    return result == ESP_OK && allowed();
  };
  const auto with_device = [&](k151::Device device, const auto& action) {
    if (!ok || !allowed()) { ok = false; return; }
    const auto i = k151::index(device);
    if (!acknowledged[i]) return;  // NACK is evidence, not readiness.
    i2c_device_config_t dc = {};
    dc.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dc.device_address = k151::kProbeAddresses[i];
    dc.scl_speed_hz = kI2cSpeedHz;
    i2c_master_dev_handle_t dev = nullptr;
    if (i2c_master_bus_add_device(bus, &dc, &dev) != ESP_OK) { ok = false; return; }
    ok = allowed() && action(dev);
    // Cleanup must still run on STOP/revocation/read error. A cleanup failure
    // invalidates the whole snapshot; no second probe/retry is attempted.
    const auto removed = i2c_master_bus_rm_device(dev);
    ok = ok && removed == ESP_OK && allowed();
  };
  if constexpr (power_only) {
    with_device(Device::pmic_axp2101, [&](auto dev) {
      return read_pmic_power([&](auto reg, auto* data, auto bytes) {
        return read(dev, reg, data, bytes);
      }, candidate);
    });
    with_device(Device::amp_aw88298, [&](auto dev) {
      return read_amp_power([&](auto reg, auto* data, auto bytes) {
        return read(dev, reg, data, bytes);
      }, candidate);
    });
  } else {
    with_device(Device::pmic_axp2101, [&](auto dev) {
      candidate.pmic_id_read = read(dev, 0x03, &candidate.pmic_id, 1);
      if (!candidate.pmic_id_read) return false;
      for (size_t i = 0; i < k151::kPmicLdoRegisters.size(); ++i) {
        if (!read(dev, k151::kPmicLdoRegisters[i], &candidate.pmic_ldo[i], 1)) return false;
      }
      candidate.pmic_ldo_read = true;
      for (size_t i = 0; i < k151::kPmicAldo12Registers.size(); ++i) {
        if (!read(dev, k151::kPmicAldo12Registers[i], &candidate.pmic_aldo12[i], 1))
          return false;
      }
      candidate.pmic_aldo12_read = true;
      return true;
    });
    with_device(Device::io_aw9523, [&](auto dev) {
      candidate.aw9523_id_read = read(dev, 0x10, &candidate.aw9523_id, 1);
      if (!candidate.aw9523_id_read) return false;
      candidate.aw9523_outputs_read = read(dev, 0x02, candidate.aw9523_outputs.data(), 2);
      if (!candidate.aw9523_outputs_read) return false;
      candidate.aw9523_directions_read = read(dev, 0x04, candidate.aw9523_directions.data(), 2);
      if (!candidate.aw9523_directions_read) return false;
      candidate.aw9523_p0_mode_read =
          read(dev, k151::kAw9523P0ModeRegister, &candidate.aw9523_p0_mode, 1);
      return candidate.aw9523_p0_mode_read;
    });
    with_device(Device::touch_ft6336, [&](auto dev) {
      candidate.touch_version_read = read(dev, kTouchVersionReg, candidate.touch_version.data(), 6);
      return candidate.touch_version_read;
    });
  }
  const auto closed = i2c_del_master_bus(bus);
  if (!ok || closed != ESP_OK || !allowed()) return false;
  if constexpr (!power_only) {
    candidate.bus_opened = true;
    candidate.acknowledged = acknowledged;
    candidate.finished_without_bus_error = true;
  }
  out = candidate;
  return true;
}
}  // namespace

const char* K151ReadOnlyProbe::compiled_link_marker() {
  return "K151 I2C diagnostic present; no startup bus/power/device access";
}

bool K151ReadOnlyProbe::observe_once(bool explicitly_authorized, const std::atomic_bool& stop,
                                    k151::ReadOnlyEvidence& out) const {
  const std::atomic_bool owner{explicitly_authorized};
  return observe_once(owner, stop, out);
}

bool K151ReadOnlyProbe::observe_once(const std::atomic_bool& owner, const std::atomic_bool& stop,
                                    k151::ReadOnlyEvidence& out) const {
  return observe(owner, stop, out);
}

bool K151ReadOnlyProbe::observe_power_once(const std::atomic_bool& owner, const std::atomic_bool& stop,
                                          k151::PowerReadback& out) const {
  return observe(owner, stop, out);
}
}  // namespace stackchan::standalone

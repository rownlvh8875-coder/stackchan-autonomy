// SPDX-License-Identifier: MIT
// Real AW88298 codec from esp_codec_dev 1.6.2 with an emulated I2C device.
#include "k151_codec_control.hpp"
#include <aw88298_dac.h>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <string_view>

using namespace stackchan::standalone;
namespace {
audio_codec_ctrl_if_t i2c{};
std::array<uint16_t, 256> registers{};
std::string_view scenario;
int writes = 0;
bool power_seen = false, mute_seen = false, volume_seen = false;
bool standby_request = false;
int standby_mute_writes = 0;

bool is_open(const audio_codec_ctrl_if_t* h) { return h == &i2c; }
int read(const audio_codec_ctrl_if_t* h, int reg, int address_bytes, void* output, int bytes) {
  assert(h == &i2c && address_bytes == 1 && bytes == 2);
  if (scenario == "read_failure" && reg == 0x05) return ESP_CODEC_DEV_READ_FAIL;
  if (standby_request && scenario == "standby_mute_read_fail" && reg == 0x05)
    return ESP_CODEC_DEV_READ_FAIL;
  auto value = registers.at(reg);
  if (scenario == "readback_mismatch" && reg == 0x05) value &= ~0x10;
  auto* data = static_cast<uint8_t*>(output);
  data[0] = static_cast<uint8_t>(value >> 8);
  data[1] = static_cast<uint8_t>(value);
  return ESP_CODEC_DEV_OK;
}
int write(const audio_codec_ctrl_if_t* h, int reg, int address_bytes, void* input, int bytes) {
  assert(h == &i2c && address_bytes == 1 && bytes == 2);
  ++writes;
  const auto* data = static_cast<const uint8_t*>(input);
  const auto word = static_cast<uint16_t>((data[0] << 8) | data[1]);
  if (scenario != "raw") {
    if (reg == 0x04) assert((word & 0x43) == 0x03);
    if (reg == 0x05) assert((word & 0x10) != 0);
    if (reg == 0x0c) assert((word >> 8) >= 0x60 && (word >> 8) <= 0xc0);
  }
  if (scenario == "write_failure" && reg == 0x05) return ESP_CODEC_DEV_WRITE_FAIL;
  if (standby_request && reg == 0x05) {
    assert(!power_seen);
    ++standby_mute_writes;
    if (scenario == "standby_mute_write_fail") return ESP_CODEC_DEV_WRITE_FAIL;
  }
  if (standby_request && reg == 0x04) {
    if (scenario == "standby_power_write_fail") return ESP_CODEC_DEV_WRITE_FAIL;
    if (scenario != "standby_still_switching") registers[0x01] &= ~0x0100;
  }
  if (reg == 0x04) power_seen = true;
  if (reg == 0x05) mute_seen = true;
  if (reg == 0x0c) volume_seen = true;
  registers.at(reg) = word;
  return ESP_CODEC_DEV_OK;
}
int info(const audio_codec_ctrl_if_t* h, audio_codec_ctrl_info_t* out) {
  assert(h == &i2c);
  out->type = AUDIO_CODEC_CTRL_I2C;
  return ESP_CODEC_DEV_OK;
}
}
extern "C" void esp_codec_dev_sleep(int) { assert(false && "AW9523 owns amp reset"); }

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  i2c.is_open = is_open;
  i2c.read_reg = read;
  i2c.write_reg = write;
  i2c.get_info = info;
  K151CodecControl guarded{scenario == "raw" ? K151CodecControl::Profile::observe
                                            : K151CodecControl::Profile::aw88298_muted_startup};
  assert(guarded.attach(&i2c));
  const auto* bus = guarded.interface();
  aw88298_codec_cfg_t config{};
  config.ctrl_if = bus;
  config.reset_pin = -1;
  config.hw_gain.pa_voltage = 5.0f;
  config.hw_gain.codec_dac_voltage = 3.3f;
  config.hw_gain.pa_gain = 1.0f;
  const auto* amp = aw88298_codec_new(&config);
  if (scenario == "raw") {
    assert(amp && (registers[0x04] & 0x43) == 0x40 && (registers[0x05] & 0x10) == 0);
  } else if (scenario == "read_failure" || scenario == "readback_mismatch" || scenario == "write_failure") {
    assert(!amp && guarded.faulted() && !guarded.muted_startup_verified());
    assert(power_seen && !volume_seen);
    // Best-effort power-down is available to the owner, but the fault stays latched.
    guarded.begin_cleanup();
    const int before = writes;
    uint8_t power_write[]{0x40, 0x40};
    assert(bus->write_reg(bus, 0x04, 1, power_write, 2) == ESP_CODEC_DEV_OK);
    assert(writes == before + 1 && power_write[1] == 0x40 && guarded.faulted());
    return 0;
  } else {
    assert(amp && guarded.muted_startup_verified() && power_seen && mute_seen && volume_seen);
    assert(amp->enable(amp, true) == ESP_CODEC_DEV_OK);
    assert(amp->mute(amp, false) == ESP_CODEC_DEV_OK);
    assert(amp->set_vol(amp, 0.0f) == ESP_CODEC_DEV_OK);
    assert(guarded.muted_startup_verified());
    assert((registers[0x04] & 0x43) == 0x03 && (registers[0x05] & 0x10) != 0);
    assert((registers[0x0c] >> 8) >= 0x60);
    if (scenario.starts_with("standby")) {
      // Begin with an emulated active register state. No physical amp is opened.
      constexpr uint16_t active_power = 0x40c4, active_mute = 0x26a8;
      registers[0x00] = 0x1852;
      registers[0x01] = 0x0100;
      registers[0x04] = active_power;
      registers[0x05] = active_mute;
      const auto attenuation = registers[0x0c];
      if (scenario == "standby_after_fault") {
        uint8_t invalid_width = 0;
        assert(bus->write_reg(bus, 0x05, 1, &invalid_width, 1) != ESP_CODEC_DEV_OK);
        assert(guarded.faulted());
      }
      power_seen = false;
      standby_request = true;
      const bool requested = guarded.request_aw88298_standby();
      standby_request = false;
      const bool mute_failed =
          scenario == "standby_mute_read_fail" || scenario == "standby_mute_write_fail";
      const bool power_failed = scenario == "standby_power_write_fail";
      assert(requested == (!mute_failed && !power_failed));
      assert(power_seen == !power_failed);
      assert(registers[0x04] == (power_failed ? active_power : (active_power & ~0x43) | 0x03));
      assert(registers[0x05] == (mute_failed ? active_mute : active_mute | 0x10));
      assert(standby_mute_writes == (scenario == "standby_mute_read_fail" ? 0 : 1));
      assert(registers[0x0c] == attenuation);
      assert(guarded.faulted() == (mute_failed || power_failed || scenario == "standby_after_fault"));
      assert(guarded.aw88298_standby_verified() == (scenario == "standby"));
      guarded.begin_cleanup();
    }
    if (scenario == "unknown_width") {
      uint8_t data = 0x08;
      const int before = writes;
      assert(bus->write_reg(bus, 0x05, 1, &data, 1) != ESP_CODEC_DEV_OK && writes == before);
      assert(!guarded.muted_startup_verified() && guarded.faulted());
      guarded.begin_cleanup();
    } else if (scenario == "reset") {
      assert(amp->set_reg(amp, 0x00, 0x55aa) == ESP_CODEC_DEV_OK);
      assert(!guarded.muted_startup_verified() && !guarded.faulted());
    }
  }
  (void)amp->close(amp);
  std::free(const_cast<audio_codec_if_t*>(amp));
}

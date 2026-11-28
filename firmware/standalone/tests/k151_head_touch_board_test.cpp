// SPDX-License-Identifier: MIT
#include "k151_head_touch_owner.hpp"

#include <array>
#include <cassert>
#include <string_view>

using namespace stackchan::standalone;

struct i2c_master_bus_t {};
struct i2c_master_dev_t {};
namespace {
i2c_master_bus_t board_bus, wrong_bus;
i2c_master_dev_t sensor;
std::atomic_bool stop_requested{false};
bool sensor_open = false;
bool warm_attach = false;
bool cleanup_failed_once = false;
bool sample_failed = false;
std::string_view scenario;
int64_t clock_us = 1000000;
unsigned writes = 0;
unsigned delays = 0;
std::array<uint8_t, 0x11> regs{};
}

extern "C" esp_err_t i2c_master_get_bus_handle(i2c_port_t port,
                                              i2c_master_bus_handle_t* out) {
  assert(port == I2C_NUM_1);
  *out = &board_bus;
  return ESP_OK;
}

extern "C" esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus,
    const i2c_device_config_t* cfg, i2c_master_dev_handle_t* out) {
  assert(bus == &board_bus && !sensor_open);
  assert(cfg->device_address == 0x68 && cfg->scl_speed_hz == 100000);
  sensor_open = true;
  *out = &sensor;
  return ESP_OK;
}

extern "C" esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t dev) {
  assert(dev == &sensor && sensor_open);
  sensor_open = false;
  return ESP_OK;
}

extern "C" esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t dev,
    const uint8_t* reg, size_t reg_len, uint8_t* output, size_t len, int timeout) {
  assert(dev == &sensor && sensor_open && reg_len == 1 && len == 1 && timeout == 100);
  if (warm_attach) assert(*reg == 0x10);
  if (scenario == "read_error" && *reg == 0x0e) return ESP_FAIL;
  if (sample_failed && *reg == 0x10) return ESP_FAIL;
  *output = regs.at(*reg);
  if (scenario == "readback_mismatch" && *reg == 0x02 && writes == 1)
    *output ^= 0x01;
  return ESP_OK;
}

extern "C" esp_err_t i2c_master_transmit(i2c_master_dev_handle_t dev,
    const uint8_t* bytes, size_t len, int timeout) {
  assert(dev == &sensor && sensor_open && len == 2 && timeout == 100);
  assert(bytes[0] == 0x02 || bytes[0] == 0x03 || bytes[0] == 0x0a ||
         bytes[0] == 0x0c || bytes[0] == 0x0e);
  ++writes;
  if (scenario == "cleanup_retry" && bytes[0] == 0x0c &&
      bytes[1] == 0xfe && !cleanup_failed_once) {
    cleanup_failed_once = true;
    return ESP_FAIL;
  }
  regs.at(bytes[0]) = bytes[1];
  if (scenario == "stop_during_write" && writes == 2) stop_requested.store(true);
  if (scenario == "ambiguous_write" && writes == 2) return ESP_FAIL;
  return ESP_OK;
}

extern "C" int64_t esp_timer_get_time() { return clock_us; }

void vTaskDelay(unsigned ticks) {
  assert(ticks >= 200);
  ++delays;
  clock_us += 1000 * ticks;
  if (scenario == "stop_during_settle") stop_requested.store(true);
  if (scenario == "clock_rollback") clock_us = 999000;
  if (scenario == "reset_during_settle") regs[0x0c] = 0xfe;
}

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  regs[0x02] = 0xbb;
  regs[0x03] = 0xbb;
  regs[0x08] = 0x22;
  regs[0x09] = 0x07;
  regs[0x0a] = 0xfe;
  regs[0x0c] = 0xfe;
  regs[0x0d] = 0x3f;
  regs[0x0e] = 0;
  if (scenario == "wrong_config") regs[0x09] = 0x0f;
  if (scenario == "clock_error") clock_us = -1000000;
  if (scenario == "poll_error") regs[0x0e] = 0xa5;
  if (scenario == "configured") {
    regs[0x02] = 0x33;
    regs[0x03] = 0x83;
    regs[0x0a] = 0xf8;
    regs[0x0c] = 0xf8;
  }
  const auto original = regs;
  std::atomic_bool owner_mode{true};
  K151HeadTouchOwner owner(owner_mode, stop_requested);
  assert(!owner_mode.load());
  if (scenario == "readonly") {
    warm_attach = true;
    assert(owner.attach_readonly(&board_bus, true, true, true, 1000));
    assert(owner.poll_once(1000) == TouchConsentEvent::none);
    assert(owner.detach());
    assert(!sensor_open && !writes && !delays);
    return 0;
  }
  if (scenario == "stopped") stop_requested.store(true);
  const bool started = owner.attach_for_setup(
      scenario == "wrong_bus" ? &wrong_bus : &board_bus,
      scenario != "unverified", scenario != "bus_not_exclusive");
  assert(!owner_mode.load());
  if (scenario == "cold" || scenario == "cleanup_retry" || scenario == "configured" ||
      scenario == "poll_error" || scenario == "stop_after_consent") {
    assert(started && sensor_open);
    assert(regs[0x02] == 0x33 && (regs[0x03] & 0x0f) == 0x03);
    assert((regs[0x03] & 0xf0) == (original[0x03] & 0xf0));
    assert(regs[0x08] == 0x22 && regs[0x09] == 0x07 && regs[0x0d] == 0x3f);
    assert(regs[0x0a] == 0xf8 && regs[0x0c] == 0xf8);
    assert(regs[0x0e] == (original[0x0e] & 0xf8));
    assert(delays == (scenario == "configured" ? 0U : 1U));
    const unsigned expected_writes = scenario == "poll_error" ? 5U : 4U;
    assert(writes == (scenario == "configured" ? 0U : expected_writes));
    auto sample = [&](uint8_t pads) {
      // In this bus model a disabled channel cannot produce a touch result.
      assert(pads == 0 || (regs[0x0c] & 0x04) == 0);
      regs[0x10] = pads;
      const auto event = owner.poll_once(static_cast<uint64_t>(clock_us / 1000));
      clock_us += 50000;
      return event;
    };
    for (int i = 0; i != 7; ++i) assert(sample(0) == TouchConsentEvent::none);
    for (int i = 0; i != 61; ++i) assert(sample(0x20) == TouchConsentEvent::none);
    for (int i = 0; i != 6; ++i) assert(sample(0) == TouchConsentEvent::none);
    assert(sample(0) == TouchConsentEvent::owner_window_open && owner_mode.load());
    if (scenario == "poll_error" || scenario == "stop_after_consent") {
      sample_failed = scenario == "poll_error";
      stop_requested.store(scenario == "stop_after_consent");
      assert(sample(0) == TouchConsentEvent::invalidated && !sensor_open);
      assert(!owner_mode.load() && !owner.owner_window_open(clock_us / 1000));
    }
    if (scenario == "cleanup_retry") assert(!owner.detach() && sensor_open);
    assert(owner.detach() && !owner_mode.load());
  } else {
    assert(!started);
    if (scenario == "wrong_bus" || scenario == "stopped" || scenario == "unverified" ||
        scenario == "bus_not_exclusive" || scenario == "wrong_config" ||
        scenario == "read_error" || scenario == "clock_error")
      assert(writes == 0 && delays == 0);
    assert(owner.poll_once(1000) != TouchConsentEvent::owner_window_open);
  }
  regs[0x10] = 0;
  assert(!sensor_open && regs == original);
}

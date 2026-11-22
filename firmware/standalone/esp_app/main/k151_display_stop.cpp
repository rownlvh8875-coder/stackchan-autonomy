// SPDX-License-Identifier: MIT
#include "k151_display_stop.hpp"

#include "board_evidence.hpp"
#include "k151_codec_port.hpp"
#include "k151_lcd_panel.hpp"
#include <array>
#include <driver/gpio.h>
#include <esp_err.h>
#include <esp_timer.h>
#include <optional>

namespace stackchan::standalone {
namespace {
constexpr gpio_num_t kIrq = GPIO_NUM_21;  // AW9523B INTN, externally pulled high.
constexpr uint8_t kInterruptMask0 = 0x06;
constexpr uint8_t kTouch = 1u << 2;  // FT6336U TOUCH_INT -> AW9523B P1_2.
constexpr int kReadTimeoutMs = 30;
constexpr uint64_t kSamplePeriodUs = 10'000;

std::atomic_bool latched{false};
bool attempted = false;
esp_timer_handle_t monitor = nullptr;
i2c_master_dev_handle_t probe = nullptr;
std::array<std::optional<uint8_t>, 2> original_masks;

bool release_probe() {
  if (!probe) return true;
  const auto result = i2c_master_bus_rm_device(probe);
  // A busy device remains attached in the pinned IDF driver.
  if (result != ESP_ERR_INVALID_STATE) probe = nullptr;
  return result == ESP_OK;
}

bool attach_probe(i2c_master_bus_handle_t bus, k151::Device device) {
  i2c_device_config_t config{};
  config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  config.device_address = k151::kProbeAddresses[k151::index(device)];
  config.scl_speed_hz = 100'000;
  return !probe && i2c_master_bus_add_device(bus, &config, &probe) == ESP_OK;
}

bool read_register(uint8_t address, uint8_t& value) {
  return i2c_master_transmit_receive(probe, &address, 1, &value, 1, kReadTimeoutMs) == ESP_OK;
}

bool read_gpio_inputs(uint8_t port, uint8_t& inputs) {
  uint8_t mode{}, direction{};
  if (!read_register(k151::kAw9523P0ModeRegister + port, mode) ||
      !read_register(0x04 + port, direction))
    return false;
  inputs = mode & direction;
  return true;
}

bool write_mask(uint8_t reg, uint8_t mask) {
  const uint8_t command[]{reg, mask};
  uint8_t observed{};
  return i2c_master_transmit(probe, command, sizeof(command), kReadTimeoutMs) == ESP_OK &&
         read_register(reg, observed) && observed == mask;
}

bool mask_other_interrupts(uint8_t port, uint8_t inputs, uint8_t allowed) {
  const auto reg = static_cast<uint8_t>(kInterruptMask0 + port);
  uint8_t before{};
  if (!read_register(reg, before)) return false;
  const auto after = static_cast<uint8_t>((before | inputs) & ~allowed);
  if (before == after) return true;
  // Record before the transaction. A write error also requires restoration.
  original_masks[port] = before;
  return write_mask(reg, after);
}

bool restore_route() {
  for (uint8_t port = 0; port < original_masks.size(); ++port) {
    auto& mask = original_masks[port];
    if (mask && write_mask(kInterruptMask0 + port, *mask)) mask.reset();
  }
  return !original_masks[0] && !original_masks[1] && release_probe();
}

bool prepare_route(i2c_master_bus_handle_t bus) {
  if (!attach_probe(bus, k151::Device::touch_ft6336)) return false;
  uint8_t mode{};
  const bool triggering = read_register(0xa4, mode) && mode == 0x01;
  if (!release_probe() || !triggering || !attach_probe(bus, k151::Device::io_aw9523)) return false;

  uint8_t id{}, p0_inputs{}, p1_inputs{};
  if (!read_register(0x10, id) || id != 0x23 ||
      !read_gpio_inputs(0, p0_inputs) || !read_gpio_inputs(1, p1_inputs) ||
      !(p1_inputs & kTouch) ||
      !mask_other_interrupts(0, p0_inputs, 0) || !mask_other_interrupts(1, p1_inputs, kTouch))
    return false;
  // Retain the expander handle only while an original mask needs restoration.
  return original_masks[0] || original_masks[1] || release_probe();
}

void sample_stop(void*) {
  // AW9523B keeps the active-low interrupt pending until input-register
  // reads. The timer task samples the pad without I2C, even during owner TLS.
  if (!latched.load() && gpio_get_level(kIrq) == 0) latched.store(true);
}
bool start_monitor() {
  gpio_config_t gpio{};
  gpio.pin_bit_mask = 1ULL << kIrq;
  gpio.mode = GPIO_MODE_INPUT;
  gpio.pull_up_en = GPIO_PULLUP_DISABLE;
  gpio.pull_down_en = GPIO_PULLDOWN_DISABLE;
  gpio.intr_type = GPIO_INTR_DISABLE;
  if (gpio_config(&gpio) != ESP_OK) return false;

  sample_stop(nullptr);
  esp_timer_create_args_t config{};
  config.callback = sample_stop;
  config.dispatch_method = ESP_TIMER_TASK;
  config.name = "display_stop";
  config.skip_unhandled_events = true;
  if (latched.load() || esp_timer_create(&config, &monitor) != ESP_OK ||
      esp_timer_start_periodic(monitor, kSamplePeriodUs) != ESP_OK)
    return false;
  sample_stop(nullptr);
  return !latched.load();
}

bool stop_monitor() {
  if (!monitor) return true;
  const auto result = esp_timer_stop(monitor);
  if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) return false;
  // Any callback already dispatched can use the static latch and pad safely.
  if (esp_timer_delete(monitor) != ESP_OK) return false;
  monitor = nullptr;
  return true;
}
} // namespace

const std::atomic_bool& K151DisplayStop::flag() { return latched; }

K151DisplayStop::ArmResult K151DisplayStop::arm(i2c_master_bus_handle_t board_bus,
                                               K151LcdPanel& panel) {
  if (attempted || latched.load() || !K151CodecPort::is_registered_board_bus(board_bus))
    return ArmResult::unavailable;
  attempted = true;
  const bool armed = panel.handoff_stop_input(board_bus, latched) &&
                     prepare_route(board_bus) && start_monitor();
  return armed ? ArmResult::armed : ArmResult::owned_unarmed;
}

bool K151DisplayStop::disarm() {
  latched.store(true);
  const bool monitor_stopped = stop_monitor();
  return restore_route() && monitor_stopped;
}

} // namespace stackchan::standalone

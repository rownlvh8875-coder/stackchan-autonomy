// SPDX-License-Identifier: MIT
#include "k151_silent_tx_probe.hpp"
#include <driver/i2s_std.h>
#include <algorithm>
#include <atomic>
#include <cassert>
#include <string_view>

using namespace stackchan::standalone;
struct i2s_channel_obj {};
namespace {
std::string_view scenario;
std::atomic_bool owner{true}, stop{false};
i2s_channel_obj channel;
uintptr_t slot_a, slot_b;
i2s_isr_callback_t callback;
void* context;
unsigned ticks, enables, disables, deletes;
bool preloaded;
int64_t now;
}

extern "C" esp_err_t i2s_new_channel(
    const i2s_chan_config_t* config, i2s_chan_handle_t* tx, i2s_chan_handle_t* rx) {
  assert(tx && !rx && config->id == I2S_NUM_0 && config->role == I2S_ROLE_MASTER);
  assert(config->dma_frame_num == 240 && config->dma_desc_num == 2);
  *tx = &channel;
  return ESP_OK;
}
extern "C" esp_err_t i2s_channel_init_std_mode(
    i2s_chan_handle_t tx, const i2s_std_config_t* config) {
  assert(tx == &channel && config->clk_cfg.sample_rate_hz == 24000);
  assert(config->slot_cfg.data_bit_width == 16 && config->slot_cfg.slot_mask == I2S_STD_SLOT_BOTH);
  const auto& pins = config->gpio_cfg;
  assert(pins.mclk == I2S_GPIO_UNUSED && pins.bclk == I2S_GPIO_UNUSED &&
         pins.ws == I2S_GPIO_UNUSED && pins.dout == I2S_GPIO_UNUSED && pins.din == I2S_GPIO_UNUSED);
  return ESP_OK;
}
extern "C" esp_err_t i2s_channel_register_event_callback(
    i2s_chan_handle_t tx, const i2s_event_callbacks_t* callbacks, void* data) {
  assert(tx == &channel && !enables && callbacks->on_sent && data);
  if (scenario == "register_failure") return ESP_FAIL;
  callback = callbacks->on_sent;
  context = data;
  return ESP_OK;
}
extern "C" esp_err_t i2s_channel_preload_data(
    i2s_chan_handle_t tx, const void* source, size_t bytes, size_t* loaded) {
  assert(tx == &channel && !enables && bytes == 1920);
  const auto* samples = static_cast<const uint8_t*>(source);
  assert(std::all_of(samples, samples + bytes, [](auto byte) { return byte == 0; }));
  preloaded = true;
  *loaded = scenario == "short_preload" ? bytes - 4 : bytes;
  return ESP_OK;
}
extern "C" esp_err_t i2s_channel_enable(i2s_chan_handle_t tx) {
  assert(tx == &channel && preloaded && callback && !enables++);
  return scenario == "enable_failure" ? ESP_FAIL : ESP_OK;
}
extern "C" esp_err_t i2s_channel_disable(i2s_chan_handle_t tx) {
  assert(tx == &channel && enables == 1 && !disables++);
  return scenario == "disable_failure" ? ESP_FAIL : ESP_OK;
}
extern "C" esp_err_t i2s_del_channel(i2s_chan_handle_t tx) {
  assert(tx == &channel && !deletes++);
  assert(!enables || disables == 1 || scenario == "enable_failure");
  return scenario == "delete_failure" ? ESP_FAIL : ESP_OK;
}
extern "C" int64_t esp_timer_get_time() { return now; }
void vTaskDelay(unsigned delay) {
  assert(delay == 1 && callback && enables == 1);
  ++ticks;
  now += 10'000;
  if (scenario == "clock_rollback") now = -1;
  if (scenario == "stop") stop = true;
  if (scenario == "owner_revoked") owner = false;
  if (scenario == "late") now = 100'001;
  if (scenario == "timeout") return;
  i2s_event_data_t event{ticks == 1 || scenario == "duplicate" ? &slot_a : &slot_b,
                         scenario == "bad_event" ? 920u : 960u};
  assert(!callback(&channel, &event, context));
  if (scenario == "late") {
    event.dma_buf = &slot_b;
    assert(!callback(&channel, &event, context));
  }
}

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  if (scenario == "denied") owner = false;
  if (scenario == "stop_before") stop = true;
  const auto result = run_k151_silent_tx_probe(owner, stop);
  using Result = K151SilentTxResult;
  if (scenario == "denied" || scenario == "stop_before") {
    assert(result == (scenario == "denied" ? Result::denied : Result::stopped));
    assert(!enables && !preloaded && !deletes);
  } else if (scenario == "timeout" || scenario == "late") {
    assert(result == Result::timeout && disables == 1 && deletes == 1);
  } else if (scenario == "duplicate" || scenario == "bad_event") {
    assert(result == Result::invalid_event && disables == 1 && deletes == 1);
  } else if (scenario == "clock_rollback") {
    assert(result == Result::clock_fault && disables == 1 && deletes == 1);
  } else if (scenario == "stop" || scenario == "owner_revoked") {
    assert(result == Result::stopped && disables == 1 && deletes == 1);
  } else if (scenario == "register_failure") {
    assert(result == Result::callback_failed && !enables && deletes == 1);
  } else if (scenario == "short_preload") {
    assert(result == Result::preload_failed && !enables && deletes == 1);
  } else if (scenario == "enable_failure") {
    assert(result == Result::enable_failed && !disables && deletes == 1);
  } else if (scenario == "disable_failure" || scenario == "delete_failure") {
    assert(result == Result::cleanup_failed && disables == 1 &&
           deletes == (scenario == "delete_failure" ? 1u : 0u));
  } else {
    assert(scenario == "ok" && result == Result::observed && ticks == 2 && disables == 1 && deletes == 1);
    assert(run_k151_silent_tx_probe(owner, stop) == Result::denied);
  }
}

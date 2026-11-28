// SPDX-License-Identifier: MIT
#include "k151_silent_tx_probe.hpp"

#include <driver/i2s_std.h>
#include <esp_attr.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <array>
#include <cstdint>

namespace stackchan::standalone {
namespace {
using Result = K151SilentTxResult;
constexpr size_t kDescriptorCount = 2;
constexpr size_t kFramesPerDescriptor = 240;
constexpr size_t kDescriptorBytes = kFramesPerDescriptor * 2 * sizeof(int16_t);
constexpr int64_t kObservationDeadlineUs = 100'000;
constexpr std::array<uint8_t, kDescriptorCount * kDescriptorBytes> kSilence{};

enum class Progress : uint32_t { waiting, first, complete, invalid };
static_assert(std::atomic<Progress>::is_always_lock_free);

struct Observation {
  std::atomic<Progress> progress{Progress::waiting};
  void* first_buffer = nullptr;  // Only accessed by this channel's DMA callback.
};

// Lifetime extends past an unverified driver teardown. No retry is supported.
DRAM_ATTR Observation observation;
std::atomic_flag attempted = ATOMIC_FLAG_INIT;

bool IRAM_ATTR on_sent(i2s_chan_handle_t, i2s_event_data_t* event, void* user) {
  auto& state = *static_cast<Observation*>(user);
  const auto progress = state.progress.load(std::memory_order_relaxed);
  if (progress == Progress::complete || progress == Progress::invalid) return false;
  if (!event || !event->dma_buf || event->size != kDescriptorBytes ||
      event->dma_buf == state.first_buffer) {
    state.progress.store(Progress::invalid, std::memory_order_release);
  } else if (progress == Progress::waiting) {
    state.first_buffer = event->dma_buf;
    state.progress.store(Progress::first, std::memory_order_release);
  } else {
    state.progress.store(Progress::complete, std::memory_order_release);
  }
  return false;
}
}  // namespace

K151SilentTxResult run_k151_silent_tx_probe(const std::atomic_bool& owner,
                                           const std::atomic_bool& stop) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (stop.load()) return Result::stopped;
  if (!owner.load() || attempted.test_and_set()) return Result::denied;

  i2s_chan_config_t config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  config.dma_desc_num = kDescriptorCount;
  config.dma_frame_num = kFramesPerDescriptor;
  i2s_chan_handle_t tx = nullptr;
  if (!allowed()) return Result::stopped;
  if (i2s_new_channel(&config, &tx, nullptr) != ESP_OK) return Result::channel_failed;

  bool enabled = false;
  const auto finish = [&](Result result) {
    if (enabled && i2s_channel_disable(tx) != ESP_OK) return Result::cleanup_failed;
    if (i2s_del_channel(tx) != ESP_OK) return Result::cleanup_failed;
    return allowed() ? result : Result::stopped;
  };

  i2s_std_config_t standard{};
  standard.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(24000);
  standard.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  standard.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
  auto& pins = standard.gpio_cfg;
  pins.mclk = pins.bclk = pins.ws = pins.dout = pins.din = I2S_GPIO_UNUSED;
  if (!allowed()) return finish(Result::stopped);
  if (i2s_channel_init_std_mode(tx, &standard) != ESP_OK) return finish(Result::channel_failed);

  i2s_event_callbacks_t callbacks{};
  callbacks.on_sent = on_sent;
  if (!allowed()) return finish(Result::stopped);
  if (i2s_channel_register_event_callback(tx, &callbacks, &observation) != ESP_OK)
    return finish(Result::callback_failed);

  size_t loaded = 0;
  if (!allowed()) return finish(Result::stopped);
  if (i2s_channel_preload_data(tx, kSilence.data(), kSilence.size(), &loaded) != ESP_OK ||
      loaded != kSilence.size()) return finish(Result::preload_failed);
  const auto started = esp_timer_get_time();
  if (started < 0) return finish(Result::clock_fault);
  if (!allowed()) return finish(Result::stopped);
  if (i2s_channel_enable(tx) != ESP_OK) return finish(Result::enable_failed);
  enabled = true;

  auto previous = started;
  for (;;) {
    if (!allowed()) return finish(Result::stopped);
    const auto progress = observation.progress.load(std::memory_order_acquire);
    const auto now = esp_timer_get_time();
    if (now < previous) return finish(Result::clock_fault);
    if (now - started >= kObservationDeadlineUs) return finish(Result::timeout);
    if (progress == Progress::invalid) return finish(Result::invalid_event);
    if (progress == Progress::complete) return finish(Result::observed);
    previous = now;
    vTaskDelay(1);
  }
}

}  // namespace stackchan::standalone

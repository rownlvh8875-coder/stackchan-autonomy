// SPDX-License-Identifier: MIT
#include "bench_gate.hpp"
#include "board_evidence.hpp"
#include "k151_board_bus.hpp"
#include "k151_display_stop.hpp"
#include "k151_head_touch_owner.hpp"
#include "k151_lcd_panel.hpp"

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <driver/usb_serial_jtag.h>
#include <esp_chip_info.h>
#include <esp_ota_ops.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
int64_t now_ms() {
  const auto now_us = esp_timer_get_time();
  return now_us < 0 ? -1 : now_us / 1000;
}
void pause_ms(unsigned ms) { vTaskDelay(pdMS_TO_TICKS(ms) + 1); }

class LocalGate final {
 public:
  explicit LocalGate(uint32_t challenge) : challenge_(challenge), gate_(challenge, now_ms(), true) {}

  bool wait_for_start() {
    while (!gate_.running() && !gate_.stopped()) {
      if (receive(pdMS_TO_TICKS(20) + 1) < 0) return false;
    }
    return gate_.running();
  }

  bool running() {
    for (unsigned count = 0; count < 32 && !gate_.stopped(); ++count) {
      const int size = receive(0);
      if (size <= 0) break;
    }
    return gate_.running();
  }

 private:
  int receive(uint32_t ticks) {
    char byte{};
    const int count = usb_serial_jtag_read_bytes(&byte, 1, ticks);
    const auto now = now_ms();
    gate_.tick(now);
    if (count == 1 && gate_.feed(byte, now))
      std::printf("{\"probe\":\"WAIT_LOCAL_START\",\"nonce\":\"%08lX\"}\n",
                  static_cast<unsigned long>(challenge_));
    if (count < 0 || count > 1) {
      (void)gate_.feed('\0', now);
      return -1;
    }
    return count;
  }

  const uint32_t challenge_;
  BenchGate gate_;
};
}

class K151PanelProbe final {
 public:
  void run(LocalGate& gate) {
    const char* result = exercise(gate);
    const bool released = release();
    std::printf("{\"result\":\"%s\",\"cleanup\":%s,\"operating_admission\":false}\n",
                result, released ? "true" : "false");
  }

 private:
  const char* exercise(LocalGate& gate) {
    if (!gate.running()) return "HOST_STOP_OR_DEADLINE";
    if (!k151::open_board_bus(bus_)) return "I2C_SETUP_FAILED";
    if (lv_is_initialized()) return "LVGL_ALREADY_OWNED";
    lv_init();
    lvgl_owned_ = lv_is_initialized();
    if (!lvgl_owned_ || !panel_.start(bus_, true)) return "PANEL_START_FAILED";
    if (!gate.running()) return "HOST_STOP_OR_DEADLINE";

    lv_obj_t* label = lv_label_create(lv_display_get_screen_active(panel_.display()));
    if (!label) return "PANEL_FRAME_FAILED";
    lv_obj_center(label);
    const auto code = static_cast<unsigned long>(esp_random() % 100000000U);
    char page[64]{};
    std::snprintf(page, sizeof(page), "DISPLAY TEST %08lu\nHold head for 3 sec and release", code);
    lv_label_set_text(label, page);
    if (!panel_.present_now()) return "PANEL_FRAME_FAILED";
    if (!gate.running()) return "HOST_STOP_OR_DEADLINE";
    // The app has passed the reviewed running slot/chip check and the same
    // board's live PMIC, AW9523B and FT6336 checks in panel_.start.
    if (!head_.attach_for_setup(bus_, panel_.ready(), true)) return "HEAD_PREPARE_FAILED";
    if (!gate.running()) return "HOST_STOP_OR_DEADLINE";
    std::puts("{\"probe\":\"PANEL_FRAME_READY\"}");

    while (gate.running()) {
      const auto event = head_.poll_once(now_ms());
      if (event == TouchConsentEvent::invalidated) return "HEAD_READ_OR_TIMING_FAILED";
      if (event == TouchConsentEvent::owner_window_open) {
        if (!gate.running()) return "HOST_STOP_OR_DEADLINE";
        std::puts("{\"probe\":\"HEAD_CONFIRMED\"}");
        std::snprintf(page, sizeof(page), "DISPLAY TEST %08lu\nWait for PC, then tap screen", code);
        lv_label_set_text(label, page);
        if (!panel_.present_now()) return "STOP_PROMPT_FRAME_FAILED";
        return observe_stop(gate);
      }
      pause_ms(50);
    }
    return "HOST_STOP_OR_DEADLINE";
  }

  const char* observe_stop(LocalGate& gate) {
    if (!gate.running()) return "HOST_STOP_OR_DEADLINE";
    const auto armed = K151DisplayStop::arm(bus_, panel_);
    stop_owned_ = armed != K151DisplayStop::ArmResult::unavailable;
    if (armed != K151DisplayStop::ArmResult::armed) return "DISPLAY_STOP_ARM_FAILED";
    // A pre-existing or settling IRQ cannot pass as the requested touch.
    const auto began = now_ms();
    while (now_ms() - began < 150 && gate.running() && !stop_.load()) pause_ms(10);
    if (!gate.running()) return "HOST_STOP_OR_DEADLINE";
    if (stop_.load()) return "EARLY_DISPLAY_IRQ";
    std::puts("{\"probe\":\"WAIT_SCREEN_STOP\"}");
    while (gate.running()) {
      if (stop_.load()) return "DISPLAY_STOP_LATCHED";
      pause_ms(10);
    }
    return "HOST_STOP_OR_DEADLINE";
  }

  bool release() {
    if (stop_owned_ && !K151DisplayStop::disarm()) return false;
    stop_owned_ = false;
    const bool head_released = head_.detach();
    const bool panel_released = panel_.shutdown();
    if (panel_released && lvgl_owned_) {
      lv_deinit();
      lvgl_owned_ = false;
    }
    if (!head_released || !panel_released) return false;
    if (bus_ && i2c_del_master_bus(bus_) != ESP_OK) return false;
    bus_ = nullptr;
    return true;
  }

  const std::atomic_bool& stop_ = K151DisplayStop::flag();
  std::atomic_bool owner_{false};
  K151LcdPanel panel_{stop_};
  K151HeadTouchOwner head_{owner_, stop_};
  i2c_master_bus_handle_t bus_ = nullptr;
  bool stop_owned_ = false;
  bool lvgl_owned_ = false;
};
} // namespace stackchan::standalone

extern "C" void app_main() {
  using namespace stackchan::standalone;
  std::puts("K151_PANEL_HEAD_STOP_PROBE_NOT_OPERATIONAL");
  esp_chip_info_t chip{};
  esp_chip_info(&chip);
  const auto* partition = esp_ota_get_running_partition();
  if (!partition || partition->type != ESP_PARTITION_TYPE_APP ||
      partition->subtype != ESP_PARTITION_SUBTYPE_APP_OTA_1 ||
      !k151::board_probe_location_allowed(partition->address, partition->size,
                                         chip.model == CHIP_ESP32S3, chip.revision)) {
    std::puts("{\"result\":\"RUNNING_LOCATION_OR_CHIP_DENIED\"}");
    return;
  }
  usb_serial_jtag_driver_config_t config{};
  config.rx_buffer_size = 128;
  config.tx_buffer_size = 1024;
  if (usb_serial_jtag_is_driver_installed() || usb_serial_jtag_driver_install(&config) != ESP_OK) {
    std::puts("{\"result\":\"USB_SETUP_FAILED\"}");
    return;
  }
  LocalGate gate(esp_random());
  if (gate.wait_for_start()) {
    // Keep owned handles alive on a failed release until reset. There is no
    // second run and no automatic reset or flash access from this image.
    static K151PanelProbe probe;
    probe.run(gate);
  } else {
    std::puts("{\"result\":\"NO_LOCAL_START\"}");
  }
  std::puts("{\"probe\":\"HOLD_UNTIL_RESET\",\"operating_admission\":false}");
  std::fflush(stdout);
  (void)usb_serial_jtag_driver_uninstall();
}

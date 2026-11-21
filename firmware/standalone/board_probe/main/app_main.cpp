// SPDX-License-Identifier: MIT
// One-shot board readback, NOT an operational StackChan application.
#include "bench_gate.hpp"
#include "k151_readonly_probe.hpp"
#include <driver/usb_serial_jtag.h>
#include <esp_chip_info.h>
#include <esp_ota_ops.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <atomic>
#include <cstdio>
using namespace stackchan::standalone;
namespace {
std::atomic_bool owner{false}, stop{false}, reader_done{false};
bool allowed() { return owner.load() && !stop.load(); }
void reader(void*) {
  const uint32_t nonce = esp_random();
  BenchGate gate{nonce, esp_timer_get_time() / 1000};
  std::printf("{\"probe\":\"WAIT_LOCAL_START\",\"nonce\":\"%08lX\",\"wait_ms\":60000}\n",
              static_cast<unsigned long>(nonce));
  while (!gate.stopped() && !reader_done.load()) {
    char c{};
    const int count = usb_serial_jtag_read_bytes(&c, 1, pdMS_TO_TICKS(20));
    const auto now = esp_timer_get_time() / 1000;
    if (count == 1) gate.feed(c, now);
    else if (count < 0) { stop = true; break; }
    else gate.tick(now);
    if (gate.running()) owner = true;
  }
  owner = false; stop = true;
  vTaskDelete(nullptr);
}
void report(const k151::ReadOnlyEvidence& e, int64_t elapsed) {
  // Fixed numeric fields only. No raw console input, MAC, NVS, keys or voice.
  std::printf("{\"probe\":\"READBACK_COMPLETED\",\"elapsed_us\":%lld,"
      "\"ack\":[%u,%u,%u,%u,%u],\"pmic_id_valid\":%u,\"pmic_id\":%u,"
      "\"pmic_ldo_valid\":%u,\"pmic_regs\":[144,148,149,151,153],"
      "\"pmic_aldo12_valid\":%u,\"pmic_aldo12_values\":[%u,%u],"
      "\"pmic_values\":[%u,%u,%u,%u,%u],\"aw_id_valid\":%u,\"aw_id\":%u,"
      "\"aw_outputs_valid\":%u,\"aw_outputs\":[%u,%u],"
      "\"aw_directions_valid\":%u,\"aw_directions\":[%u,%u],"
      "\"aw_p0_mode_valid\":%u,\"aw_p0_mode\":%u,"
      "\"touch_valid\":%u,\"touch_version\":[%u,%u,%u,%u,%u,%u],"
      "\"operating_admission\":false}\n",
      static_cast<long long>(elapsed),
      unsigned(e.acknowledged[0]), unsigned(e.acknowledged[1]), unsigned(e.acknowledged[2]),
      unsigned(e.acknowledged[3]), unsigned(e.acknowledged[4]),
      unsigned(e.pmic_id_read), unsigned(e.pmic_id), unsigned(e.pmic_ldo_read),
      unsigned(e.pmic_aldo12_read), unsigned(e.pmic_aldo12[0]), unsigned(e.pmic_aldo12[1]),
      unsigned(e.pmic_ldo[0]), unsigned(e.pmic_ldo[1]), unsigned(e.pmic_ldo[2]),
      unsigned(e.pmic_ldo[3]), unsigned(e.pmic_ldo[4]),
      unsigned(e.aw9523_id_read), unsigned(e.aw9523_id), unsigned(e.aw9523_outputs_read),
      unsigned(e.aw9523_outputs[0]), unsigned(e.aw9523_outputs[1]),
      unsigned(e.aw9523_directions_read), unsigned(e.aw9523_directions[0]), unsigned(e.aw9523_directions[1]),
      unsigned(e.aw9523_p0_mode_read), unsigned(e.aw9523_p0_mode),
      unsigned(e.touch_version_read), unsigned(e.touch_version[0]), unsigned(e.touch_version[1]),
      unsigned(e.touch_version[2]), unsigned(e.touch_version[3]), unsigned(e.touch_version[4]),
      unsigned(e.touch_version[5]));
}
}
extern "C" void app_main() {
  std::puts("K151_READONLY_BOARD_PROBE_NOT_OPERATIONAL");
  esp_chip_info_t chip{};
  esp_chip_info(&chip);
  const auto* partition = esp_ota_get_running_partition();
  if (partition) {
    std::printf("{\"partition_present\":true,\"running_offset\":%lu,\"running_size\":%lu,"
                "\"chip_model\":%u,\"chip_revision\":%u}\n",
        static_cast<unsigned long>(partition->address), static_cast<unsigned long>(partition->size),
        unsigned(chip.model), unsigned(chip.revision));
  } else {
    std::printf("{\"partition_present\":false,\"running_offset\":null,\"running_size\":null,"
                "\"chip_model\":%u,\"chip_revision\":%u}\n", unsigned(chip.model), unsigned(chip.revision));
  }
  if (!partition || !k151::board_probe_location_allowed(partition->address, partition->size,
                      chip.model == CHIP_ESP32S3, chip.revision)) {
    std::puts("{\"result\":\"RUNNING_LOCATION_OR_CHIP_DENIED\"}"); return;
  }
  usb_serial_jtag_driver_config_t cfg{};
  cfg.rx_buffer_size = 128; cfg.tx_buffer_size = 1024;
  if (usb_serial_jtag_driver_install(&cfg) != ESP_OK) return;
  if (xTaskCreate(reader, "board_consent", 4096, nullptr, 6, nullptr) != pdPASS) return;
  while (!owner.load() && !stop.load()) vTaskDelay(pdMS_TO_TICKS(10));
  if (allowed()) {
    k151::ReadOnlyEvidence evidence{};
    const auto before = esp_timer_get_time();
    const bool ok = K151ReadOnlyProbe{}.observe_once(owner, stop, evidence);
    const auto elapsed = esp_timer_get_time() - before;
    if (ok && allowed() && elapsed >= 0) report(evidence, elapsed);
    else std::puts("{\"result\":\"READBACK_STOPPED_OR_FAILED\"}");
  }
  owner = false; stop = true; reader_done = true;
  std::puts("{\"probe\":\"HOLD_UNTIL_RESET\",\"operating_admission\":false}");
}

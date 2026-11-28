// SPDX-License-Identifier: MIT
#include "board_probe_sdk.hpp"
#include "k151_readonly_probe.hpp"
#include <cassert>
#include <chrono>
#include <string>
#include <string_view>
#include <thread>
std::string scenario;
namespace {
std::thread reader_task;
}
void esp_chip_info(esp_chip_info_t* chip) {
  chip->model = scenario == "chip" ? 1 : 9;
  chip->revision = scenario == "revision" ? 3 : 2;
}
const esp_partition_t* esp_ota_get_running_partition() {
  static esp_partition_t partition{scenario == "slot" ? 0x20000u : 0x510000u, 0x4f0000};
  return scenario == "missing" ? nullptr : &partition;
}
uint32_t esp_random() { assert(scenario == "report"); return 1; }
int64_t esp_timer_get_time() {
  assert(scenario == "report");
  static const auto start = std::chrono::steady_clock::now();
  return std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now() - start).count();
}
int usb_serial_jtag_read_bytes(void* out, size_t size, unsigned) {
  assert(scenario == "report" && size == 1);
#ifdef STACKCHAN_K151_POWER_READBACK
  constexpr std::string_view start = "HELLO\nSTART 00000001\n";
#else
  constexpr std::string_view start = "START 00000001\n";
#endif
  static size_t pos = 0;
  if (pos < start.size()) {
    *static_cast<char*>(out) = start[pos++];
    return 1;
  }
  std::this_thread::sleep_for(std::chrono::milliseconds(1));
  return 0;
}
int usb_serial_jtag_driver_install(const usb_serial_jtag_driver_config_t*) {
  assert(scenario == "report"); return ESP_OK;
}
int xTaskCreate(void (*entry)(void*), const char*, unsigned, void* arg, unsigned, void*) {
  assert(scenario == "report");
  reader_task = std::thread(entry, arg);
  return pdPASS;
}
void vTaskDelete(void*) { assert(scenario == "report"); }
void vTaskDelay(unsigned) { std::this_thread::sleep_for(std::chrono::milliseconds(1)); }
bool stackchan::standalone::K151ReadOnlyProbe::observe_once(const std::atomic_bool& owner,
    const std::atomic_bool& stop, k151::ReadOnlyEvidence& evidence) const {
  assert(scenario == "report" && owner.load() && !stop.load());
  evidence.acknowledged = {true, true, true, false, true};
  evidence.pmic_id_read = true;
  evidence.pmic_id = 0x4A;
  evidence.pmic_ldo_read = evidence.pmic_aldo12_read = true;
  evidence.pmic_ldo = {0xBF, 0x1C, 0x1C, 0x1C, 0x1A};
  evidence.pmic_aldo12 = {0x0D, 0x1C};
  evidence.aw9523_id_read = true;
  evidence.aw9523_id = 0x23;
  evidence.aw9523_outputs_read = evidence.aw9523_directions_read = true;
  evidence.aw9523_outputs = {0x07, 0x83};
  evidence.aw9523_directions = {0x18, 0x0C};
  evidence.aw9523_p0_mode_read = true;
  evidence.aw9523_p0_mode = 0xFD;
  evidence.touch_version_read = true;
  evidence.touch_version = {0x64, 0x01, 0x01, 0x12, 0x00, 0x11};
  return true;
}
bool stackchan::standalone::K151ReadOnlyProbe::observe_power_once(const std::atomic_bool& owner,
    const std::atomic_bool& stop, k151::PowerReadback& evidence) const {
  assert(scenario == "report" && owner.load() && !stop.load());
  using k151::PowerSample;
  evidence = {PowerSample::sampled, 3700, PowerSample::reset_value, 0, true, true};
  return true;
}
extern "C" void app_main();
int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  app_main();
  if (reader_task.joinable()) reader_task.join();
}

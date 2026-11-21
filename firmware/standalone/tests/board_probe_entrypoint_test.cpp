// SPDX-License-Identifier: MIT
#include "board_probe_sdk.hpp"
#include "k151_readonly_probe.hpp"
#include <cassert>
#include <string>
std::string scenario;
void esp_chip_info(esp_chip_info_t* chip) {
  chip->model = scenario == "chip" ? 1 : 9;
  chip->revision = scenario == "revision" ? 3 : 2;
}
const esp_partition_t* esp_ota_get_running_partition() {
  static esp_partition_t partition{scenario == "slot" ? 0x20000u : 0x510000u, 0x4f0000};
  return scenario == "missing" ? nullptr : &partition;
}
uint32_t esp_random() { assert(false); return 1; }
int64_t esp_timer_get_time() { assert(false); return 0; }
int usb_serial_jtag_read_bytes(void*, size_t, unsigned) { assert(false); return -1; }
int usb_serial_jtag_driver_install(const usb_serial_jtag_driver_config_t*) { assert(false); return -1; }
int xTaskCreate(void (*)(void*), const char*, unsigned, void*, unsigned, void*) { assert(false); return -1; }
void vTaskDelete(void*) { assert(false); }
void vTaskDelay(unsigned) { assert(false); }
bool stackchan::standalone::K151ReadOnlyProbe::observe_once(const std::atomic_bool&,
    const std::atomic_bool&, k151::ReadOnlyEvidence&) const { assert(false); return false; }
extern "C" void app_main();
int main(int argc, char** argv) { assert(argc == 2); scenario = argv[1]; app_main(); }

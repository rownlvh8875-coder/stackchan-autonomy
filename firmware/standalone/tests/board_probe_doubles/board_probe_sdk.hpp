// SPDX-License-Identifier: MIT
// Narrow host declarations; SDK implementations live only in the test.
#pragma once
#include <cstddef>
#include <cstdint>
constexpr int ESP_OK = 0, pdPASS = 1, CHIP_ESP32S3 = 9;
#define pdMS_TO_TICKS(value) (value)
struct esp_chip_info_t { int model; uint16_t revision; };
constexpr int ESP_PARTITION_TYPE_APP = 0, ESP_PARTITION_SUBTYPE_APP_OTA_1 = 17;
struct esp_partition_t {
  uint32_t address, size;
  int type = ESP_PARTITION_TYPE_APP;
  int subtype = ESP_PARTITION_SUBTYPE_APP_OTA_1;
};
struct usb_serial_jtag_driver_config_t { size_t rx_buffer_size, tx_buffer_size; };
void esp_chip_info(esp_chip_info_t*);
const esp_partition_t* esp_ota_get_running_partition();
uint32_t esp_random();
int64_t esp_timer_get_time();
int usb_serial_jtag_read_bytes(void*, size_t, unsigned);
int usb_serial_jtag_driver_install(const usb_serial_jtag_driver_config_t*);
int xTaskCreate(void (*)(void*), const char*, unsigned, void*, unsigned, void*);
void vTaskDelete(void*);
void vTaskDelay(unsigned);

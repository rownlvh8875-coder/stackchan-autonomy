// SPDX-License-Identifier: MIT
// Host double only. Actual IDF header and ABI are checked by ESP32-S3 CI.
#pragma once
extern "C" {
typedef struct esp_flash_t esp_flash_t;
extern esp_flash_t* esp_flash_default_chip;
}

// SPDX-License-Identifier: MIT
// Only declarations consumed by this adapter; not a copied vendor ABI header.
#pragma once
#include "esp_flash.h"
#include <cstdint>
extern "C" {
using esp_err_t = int;
inline constexpr esp_err_t ESP_OK = 0;
enum esp_partition_type_t { ESP_PARTITION_TYPE_APP=0, ESP_PARTITION_TYPE_DATA=1 };
enum esp_partition_subtype_t { ESP_PARTITION_SUBTYPE_ANY=255 };
struct esp_partition_t {
  esp_flash_t* flash_chip;
  esp_partition_type_t type;
  esp_partition_subtype_t subtype;
  uint32_t address, size;
  char label[17];
  bool encrypted, readonly;
};
const esp_partition_t* esp_partition_find_first(esp_partition_type_t,
                                               esp_partition_subtype_t,
                                               const char*);
esp_err_t esp_partition_get_sha256(const esp_partition_t*, uint8_t*);
}
